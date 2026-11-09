# speaker_split.py
"""Align Whisper output to diarization turns and split text by speaker.

Given transcription segments (with optional word-level timestamps) and
speaker turns from diarization, produces one text block per contiguous
speaker run.  Speaker labels are used only to group — no identity is exposed.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SpeakerTurn = Tuple[float, float, str]

# Punctuation-ending words are hard-tier split points: speaker changes almost
# always coincide with sentence ends, and a mid-sentence split is the most
# visible kind of error. When a sentence end exists within the wider window
# it wins unconditionally — only pauseless/no-punctuation regions fall back
# to inter-word gaps and word starts.
_PUNCT_WINDOW_MULT = 5.0
_WEAK_WINDOW_MULT = 3.0
# Strong sentence ends outrank weak ones — turn-start vocatives ("Hey,",
# "Oh,", "Um,") end with commas but are not turn boundaries.
_PUNCT_STRONG_RE = re.compile(r"[.!?…]+[\"')]*$")
_PUNCT_WEAK_RE = re.compile(r"[,;:]+[\"')]*$")


def _join_words(word_texts: List[str]) -> str:
    """Rejoin word strings emitted by faster-whisper / API word timestamps."""
    joined = "".join(word_texts)
    if " " not in joined and len(word_texts) > 1:
        # Word strings carry no leading-space convention — join explicitly.
        joined = " ".join(word_texts)
    return re.sub(r"\s+", " ", joined).strip()


def _speaker_at(t: float, turns: List[SpeakerTurn]) -> Optional[str]:
    """Speaker active at time t, or the nearest turn's speaker for gaps.

    Turns can overlap (pyannote detects interjections nested inside a longer
    turn) — among containing turns the tightest interval wins, so a short
    "Yeah" inside someone's monologue keeps its own speaker.
    """
    containing = [tr for tr in turns if tr[0] <= t <= tr[1]]
    if containing:
        return min(containing, key=lambda tr: tr[1] - tr[0])[2]
    if not turns:
        return None
    nearest = min(turns, key=lambda tr: min(abs(t - tr[0]), abs(t - tr[1])))
    return nearest[2]


def _refine_boundaries(
    words: List[Tuple[float, float, str]],
    turns: List[SpeakerTurn],
    shift_s: float,
    snap_s: float,
) -> List[SpeakerTurn]:
    """Compensate diarization's boundary lag.

    Turn starts systematically trail the true speech onset, so a turn's first
    word ("I", "Oh") is aligned to the previous speaker.  Each turn start is
    shifted earlier by `shift_s`, then snapped to the closest inter-word gap
    within `snap_s` so splits land on natural pauses.
    """
    if not turns:
        return turns
    # Snap candidates, by reliability:
    #  - ends of punctuation-bearing words (sentence ends — speaker changes
    #    virtually always coincide with them; weighted strongly)
    #  - inter-word gap midpoints (real acoustic pauses)
    #  - word starts (fallback for pauseless turn onsets)
    # Punctuation-only tokens ("?", "!") are excluded — whisper's timing for
    # them is least reliable and they carry no acoustic content.
    strong_cands, weak_cands, other_cands = [], [], []
    for j, (w_start, w_end, text) in enumerate(words):
        if not re.search(r"\w", text):
            continue
        if _PUNCT_STRONG_RE.search(text):
            strong_cands.append(w_end)
        elif _PUNCT_WEAK_RE.search(text):
            weak_cands.append(w_end)
        if j + 1 < len(words) and words[j + 1][0] > w_end:
            other_cands.append((w_end + words[j + 1][0]) / 2.0)
        other_cands.append(w_start)

    # Diarization boundaries lag, so the true split is usually *behind* the
    # reported boundary — earlier candidates get a mild directional bonus.
    def _score(pos: float, ref: float) -> float:
        return abs(pos - ref) if pos <= ref else abs(pos - ref) * 1.5

    def _snap(start: float, cands, window):
        hits = [p for p in cands if abs(p - start) <= window]
        return min(hits, key=lambda p: _score(p, start)) if hits else start

    punct_window = snap_s * _PUNCT_WINDOW_MULT
    weak_window = snap_s * _WEAK_WINDOW_MULT
    refined = [turns[0]]
    for start, end, label in turns[1:]:
        start -= shift_s
        snapped = _snap(start, strong_cands, punct_window)
        if snapped == start:
            snapped = _snap(start, weak_cands, weak_window)
            if snapped == start:
                snapped = _snap(start, other_cands, snap_s)
        start = snapped
        # The boundary is shared: pulling this turn's start earlier means the
        # previous turn ended earlier too — otherwise the turns overlap and
        # onset words resolve to the first (wrong) turn. Skip the clamp when
        # the new turn is nested inside the previous one (an interjection
        # inside a monologue) — the outer turn continues past it.
        prev_start, prev_end, prev_label = refined[-1]
        if prev_end <= end:
            prev_end = max(prev_start, min(prev_end, start))
            refined[-1] = (prev_start, prev_end, prev_label)
        refined.append((start, end, label))
    return refined


def _blocks_from_words(
    segments: List[Dict[str, Any]], turns: List[SpeakerTurn],
    boundary_shift_s: float = 0.0, boundary_snap_s: float = 0.0,
) -> List[Dict[str, Any]]:
    """Group words by speaker turn; one block per contiguous speaker run."""
    words = [
        (w.get("start"), w.get("end"), w.get("word") or "")
        for seg in segments
        for w in (seg.get("words") or [])
        if w.get("start") is not None
    ]
    if not words:
        return []

    turns = _refine_boundaries(words, turns, boundary_shift_s, boundary_snap_s)

    blocks: List[Dict[str, Any]] = []
    for start, end, word in words:
        speaker = _speaker_at((start + (end or start)) / 2.0, turns)
        if blocks and blocks[-1]["speaker"] == speaker:
            blocks[-1]["word_texts"].append(word)
            blocks[-1]["end"] = end
        else:
            blocks.append(
                {
                    "speaker": speaker,
                    "word_texts": [word],
                    "start": start,
                    "end": end,
                }
            )
    for block in blocks:
        block["text"] = _join_words(block.pop("word_texts"))
    return blocks


def _blocks_from_segments(
    segments: List[Dict[str, Any]], turns: List[SpeakerTurn]
) -> List[Dict[str, Any]]:
    """Fallback: assign each whisper segment to its dominant-overlap turn."""
    blocks: List[Dict[str, Any]] = []
    for seg in segments:
        seg_start, seg_end = seg.get("start"), seg.get("end")
        if seg_start is None or seg_end is None or not (seg.get("text") or "").strip():
            continue
        best_label, best_overlap = None, 0.0
        for start, end, label in turns:
            overlap = max(0.0, min(seg_end, end) - max(seg_start, start))
            if overlap > best_overlap:
                best_label, best_overlap = label, overlap
        if best_label is None:
            best_label = _speaker_at((seg_start + seg_end) / 2.0, turns)

        if blocks and blocks[-1]["speaker"] == best_label:
            blocks[-1]["text"] += " " + seg["text"].strip()
            blocks[-1]["end"] = seg_end
        else:
            blocks.append(
                {
                    "speaker": best_label,
                    "text": seg["text"].strip(),
                    "start": seg_start,
                    "end": seg_end,
                }
            )
    return blocks


def _merge_short_blocks(
    blocks: List[Dict[str, Any]], min_turn_s: float
) -> List[Dict[str, Any]]:
    """Absorb blocks shorter than min_turn_s into a neighbouring block."""
    merged = list(blocks)
    changed = True
    while changed and len(merged) > 1:
        changed = False
        for i, block in enumerate(merged):
            if (block["end"] or 0) - (block["start"] or 0) < min_turn_s:
                if i == 0:
                    target = merged[1]
                    target["start"] = block["start"]
                    target["text"] = f"{block['text']} {target['text']}".strip()
                else:
                    target = merged[i - 1]
                    target["end"] = block["end"]
                    target["text"] = f"{target['text']} {block['text']}".strip()
                merged.pop(i)
                changed = True
                break
    return merged


def split_text_by_speaker(
    segments: List[Dict[str, Any]],
    turns: List[SpeakerTurn],
    min_turn_s: float = 0.8,
    boundary_shift_s: float = 0.0,
    boundary_snap_s: float = 0.0,
) -> List[Dict[str, Any]]:
    """Split transcription text into one block per contiguous speaker run.

    Returns [{"text", "start", "speaker"}, ...] when 2+ speakers are detected,
    or [] for single-speaker/empty input (caller emits one normal topic).

    boundary_shift_s/boundary_snap_s compensate diarization's systematic
    boundary lag — see _refine_boundaries.
    """
    if not segments or not turns:
        return []

    blocks = _blocks_from_words(segments, turns, boundary_shift_s, boundary_snap_s)
    if not blocks:
        # Segment-level fallback: no word gaps to snap to, but the shift
        # still corrects the systematic lag. The boundary is shared, so the
        # previous turn's end retreats with the shifted start.
        shifted = [turns[0]]
        for s, e, l in turns[1:]:
            s -= boundary_shift_s
            ps, pe, pl = shifted[-1]
            shifted[-1] = (ps, max(ps, min(pe, s)), pl)
            shifted.append((s, e, l))
        blocks = _blocks_from_segments(segments, shifted)
    blocks = _merge_short_blocks(blocks, min_turn_s)

    if len({b["speaker"] for b in blocks}) < 2:
        return []

    return [
        {"text": b["text"], "start": b["start"], "speaker": b["speaker"]}
        for b in blocks
        if b.get("text")
    ]
