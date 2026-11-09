"""Tests for the turbo-hallucination defenses and speaker splitting.

Covers the new junk-text rules (foreign scripts, filler-only, hotwords-only,
degenerate repetition), the per-segment confidence filter, the client-side
speech gate, and the speaker-split alignment logic.

The real-world strings below are taken from an actual turbo-model session
(topics_20261105_120149.txt) where the ME microphone captured only
breathing/room noise — every [ME] entry in that file was a hallucination.
"""

import pytest

from transcription_strategies import (
    apply_hallucination_filter,
    process_whisper_segments,
    _fields_are_confident,
)


class _FakeSegment:
    """Minimal stand-in for a faster-whisper segment object."""
    def __init__(self, text, no_speech_prob=None, avg_logprob=None,
                 compression_ratio=None):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob
        self.compression_ratio = compression_ratio


PROMPT = "The following is a spoken transcript. Use proper capitalization and punctuation."


# ---------------------------------------------------------------------------
# New text-junk rules — real turbo hallucinations from the sample session
# ---------------------------------------------------------------------------

def test_filler_only_mh_filtered():
    assert apply_hallucination_filter("Mh, mh, mh, mh, mh, mh.") == ""

def test_filler_only_mm_filtered():
    assert apply_hallucination_filter("Mm-mm-mm-mm.") == ""

def test_consecutive_word_repeat_filtered():
    assert apply_hallucination_filter(
        "clipping Cognition Party racer clip clip clip clip clip clip clip clip clip"
    ) == ""

def test_phrase_repetition_filtered():
    assert apply_hallucination_filter(
        "Select the product. Select the product. Select the product. "
        "Select the product. Select the product. Select the product."
    ) == ""

def test_hotwords_only_echo_filtered():
    assert apply_hallucination_filter("Claude Code Sonnet") == ""

def test_hotword_repeats_filtered():
    assert apply_hallucination_filter(
        "The final is the file. Claude Claude. Claude Claude. Claude Claude."
    ) == ""

def test_cjk_junk_filtered():
    assert apply_hallucination_filter("clippingいました. Cognition Party racer") == ""

def test_mixed_foreign_script_filtered():
    assert apply_hallucination_filter(
        "Gret 같습니다. The total открывée text is simple."
    ) == ""

def test_subtitled_by_filtered():
    assert apply_hallucination_filter("Subtitled by") == ""


# ---------------------------------------------------------------------------
# Real speech must survive
# ---------------------------------------------------------------------------

def test_real_speech_survives():
    text = "So I want to kind of do a little review of kind of what we talked about last week."
    assert apply_hallucination_filter(text, PROMPT) == text

def test_question_with_filler_word_survives():
    # "um" inside a real sentence must not trip the filler-only rule.
    text = "Um, Kevin, do you want to take the value ladder?"
    assert apply_hallucination_filter(text) == text

def test_text_with_hotword_among_speech_survives():
    # Not *only* hotwords — this is (invented but) English-shaped text.
    text = "Entift Pooja"
    assert apply_hallucination_filter(text) == text

def test_accented_latin_survives():
    # Accented Latin letters are not foreign scripts.
    text = "The café discussion about naïve résumé screening continued."
    assert apply_hallucination_filter(text) == text


# ---------------------------------------------------------------------------
# Segment confidence filter
# ---------------------------------------------------------------------------

def test_fields_confident_normal():
    assert _fields_are_confident(0.1, -0.3, 1.5) is True

def test_fields_high_no_speech_and_low_logprob_dropped():
    assert _fields_are_confident(0.9, -0.8, 1.0) is False

def test_fields_high_no_speech_alone_kept():
    # Whisper semantics: both signals required for the no-speech drop.
    assert _fields_are_confident(0.9, -0.3, 1.0) is True

def test_fields_very_low_logprob_dropped():
    assert _fields_are_confident(0.3, -1.2, 1.0) is False

def test_fields_high_compression_dropped():
    assert _fields_are_confident(0.3, -0.5, 3.0) is False

def test_fields_missing_metadata_kept():
    assert _fields_are_confident(None, None, None) is True

def test_process_segments_drops_low_confidence():
    segments = [
        _FakeSegment(" Random noise decode.", no_speech_prob=0.95, avg_logprob=-0.9),
        _FakeSegment(" And then we discussed the budget.", avg_logprob=-0.4),
    ]
    assert process_whisper_segments(segments, PROMPT) == "And then we discussed the budget."

def test_process_segments_drops_degenerate_decode():
    segments = [_FakeSegment(" clip clip clip clip clip.", avg_logprob=-1.4)]
    assert process_whisper_segments(segments, PROMPT) == ""

def test_process_segments_missing_metadata_kept():
    # Plain test doubles (no decoder metadata) must pass through.
    class BareSegment:
        text = " Real speech without metadata."
    assert process_whisper_segments([BareSegment()], PROMPT) == "Real speech without metadata."


# ---------------------------------------------------------------------------
# Speech gate
# ---------------------------------------------------------------------------

def test_speech_gate_skips_noise(monkeypatch):
    import faster_whisper.audio, faster_whisper.vad
    monkeypatch.setattr(faster_whisper.audio, "decode_audio",
                        lambda *a, **k: [0.0] * 16000)
    monkeypatch.setattr(faster_whisper.vad, "get_speech_timestamps",
                        lambda *a, **k: [])
    import speech_gate
    monkeypatch.setattr(speech_gate, "_availability", True)
    assert speech_gate.contains_speech(b"wav", min_speech_s=0.4, threshold=0.5) is False

def test_speech_gate_passes_speech(monkeypatch):
    import faster_whisper.audio, faster_whisper.vad
    monkeypatch.setattr(faster_whisper.audio, "decode_audio",
                        lambda *a, **k: [0.0] * 16000)
    monkeypatch.setattr(faster_whisper.vad, "get_speech_timestamps",
                        lambda *a, **k: [{"start": 0, "end": 16000}])
    import speech_gate
    monkeypatch.setattr(speech_gate, "_availability", True)
    assert speech_gate.contains_speech(b"wav", min_speech_s=0.4, threshold=0.5) is True

def test_speech_gate_failure_proceeds(monkeypatch):
    import faster_whisper.audio
    def boom(*a, **k):
        raise RuntimeError("decode failed")
    monkeypatch.setattr(faster_whisper.audio, "decode_audio", boom)
    import speech_gate
    monkeypatch.setattr(speech_gate, "_availability", True)
    assert speech_gate.contains_speech(b"wav", min_speech_s=0.4, threshold=0.5) is None


# ---------------------------------------------------------------------------
# Speaker splitting (pure alignment logic — no models)
# ---------------------------------------------------------------------------

from speaker_split import split_text_by_speaker

TURNS_AB = [(0.0, 4.0, "A"), (4.0, 8.0, "B")]


def _seg(text, start, end, words):
    return {"start": start, "end": end, "text": text, "words": words}


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_split_two_speakers_word_level():
    segments = [_seg(
        " Hello there. Sounds good.",
        0.0, 8.0,
        [_w(" Hello", 0.0, 1.0), _w(" there.", 1.0, 4.0),
         _w(" Sounds", 4.5, 5.0), _w(" good.", 5.0, 8.0)],
    )]
    blocks = split_text_by_speaker(segments, TURNS_AB, min_turn_s=0.5)
    assert len(blocks) == 2
    assert blocks[0]["text"] == "Hello there."
    assert blocks[1]["text"] == "Sounds good."

def test_split_single_speaker_returns_empty():
    segments = [_seg(
        " Hello there.", 0.0, 4.0,
        [_w(" Hello", 0.0, 1.0), _w(" there.", 1.0, 4.0)],
    )]
    turns = [(0.0, 4.0, "A")]
    assert split_text_by_speaker(segments, turns) == []

def test_split_segment_level_fallback():
    # No word timestamps — segments map to dominant-overlap turn.
    segments = [
        _seg(" First part.", 0.0, 3.5, []),
        _seg(" Second part.", 4.5, 8.0, []),
    ]
    blocks = split_text_by_speaker(segments, TURNS_AB, min_turn_s=0.5)
    assert len(blocks) == 2
    assert blocks[0]["text"] == "First part."
    assert blocks[1]["text"] == "Second part."

def test_split_short_turn_merges():
    # A 0.3s "yeah" interjection merges instead of making its own topic.
    segments = [_seg(
        " Long speech yeah continued.",
        0.0, 8.0,
        [_w(" Long", 0.0, 2.0), _w(" speech", 2.0, 4.0),
         _w(" yeah", 4.0, 4.3), _w(" continued.", 4.3, 8.0)],
    )]
    turns = [(0.0, 4.0, "A"), (4.0, 4.3, "B"), (4.3, 8.0, "A")]
    blocks = split_text_by_speaker(segments, turns, min_turn_s=0.8)
    # B's micro-turn merges into A → single speaker → no split
    assert blocks == []

def test_split_alternating_speakers():
    segments = [_seg(
        " Question one answer one question two.",
        0.0, 12.0,
        [_w(" Question", 0.0, 2.0), _w(" one", 2.0, 4.0),
         _w(" answer", 4.0, 6.0), _w(" one", 6.0, 8.0),
         _w(" question", 8.0, 10.0), _w(" two.", 10.0, 12.0)],
    )]
    turns = [(0.0, 4.0, "A"), (4.0, 8.0, "B"), (8.0, 12.0, "A")]
    blocks = split_text_by_speaker(segments, turns, min_turn_s=0.5)
    assert len(blocks) == 3
    assert blocks[0]["text"] == "Question one"
    assert blocks[1]["text"] == "answer one"
    assert blocks[2]["text"] == "question two."

def test_split_empty_inputs():
    assert split_text_by_speaker([], TURNS_AB) == []
    assert split_text_by_speaker([_seg(" x", 0, 1, [])], []) == []


# --- Boundary refinement (diarization lag compensation) -------------------

def test_boundary_snap_rescues_turn_onset_word():
    # Turn B nominally starts at 4.0 but its first word "I" (3.9-4.05) has its
    # midpoint inside A's turn — without refinement it lands in speaker A's
    # block. Shift+snap moves the boundary to the 3.8-3.9 gap.
    segments = [_seg(
        " What's one thing? I once stole a penguin.",
        0.0, 8.0,
        [_w(" What's", 0.0, 2.0), _w(" one", 2.0, 3.0), _w(" thing?", 3.0, 3.8),
         _w(" I", 3.9, 4.05), _w(" once", 4.1, 5.0), _w(" stole", 5.0, 6.0),
         _w(" a", 6.0, 6.3), _w(" penguin.", 6.3, 8.0)],
    )]
    blocks = split_text_by_speaker(
        segments, TURNS_AB, min_turn_s=0.5,
        boundary_shift_s=0.15, boundary_snap_s=0.35,
    )
    assert len(blocks) == 2
    assert blocks[0]["text"] == "What's one thing?"
    assert blocks[1]["text"].startswith("I once stole")

def test_boundary_without_snap_keeps_lag():
    # Same setup, refinement disabled — the "I" lands in the previous block.
    segments = [_seg(
        " What's one thing? I once stole a penguin.",
        0.0, 8.0,
        [_w(" What's", 0.0, 2.0), _w(" one", 2.0, 3.0), _w(" thing?", 3.0, 3.8),
         _w(" I", 3.9, 4.05), _w(" once", 4.1, 5.0), _w(" stole", 5.0, 6.0),
         _w(" a", 6.0, 6.3), _w(" penguin.", 6.3, 8.0)],
    )]
    blocks = split_text_by_speaker(
        segments, TURNS_AB, min_turn_s=0.5,
        boundary_shift_s=0.0, boundary_snap_s=0.0,
    )
    assert len(blocks) == 2
    assert blocks[0]["text"].endswith("I")
    assert blocks[1]["text"].startswith("once")

def test_boundary_snaps_to_word_start_when_no_gap():
    # Continuous speech: "Oh" runs straight into "my god" with no pause, and
    # the lagged turn boundary sits *after* Oh's midpoint. The word start is
    # the only snap candidate and rescues it.
    segments = [_seg(
        " stole a penguin. Oh my god, how long ago?",
        0.0, 8.0,
        [_w(" stole", 0.0, 1.5), _w(" a", 1.5, 1.8), _w(" penguin.", 1.8, 3.8),
         _w(" Oh", 3.9, 4.2), _w(" my", 4.25, 4.6), _w(" god,", 4.65, 5.2),
         _w(" how", 5.3, 5.7), _w(" long", 5.75, 6.1), _w(" ago?", 6.15, 6.6)],
    )]
    # Boundary at 4.6 (past Oh's midpoint 4.05) — Oh belongs to turn A without
    # refinement; shift 0.15 puts it at 4.45, still past Oh's start; Oh's start
    # (3.9) is the nearest candidate within 0.35.
    blocks = split_text_by_speaker(
        segments, [(0.0, 4.6, "A"), (4.6, 8.0, "B")], min_turn_s=0.5,
        boundary_shift_s=0.15, boundary_snap_s=0.6,
    )
    assert len(blocks) == 2
    assert blocks[0]["text"] == "stole a penguin."
    assert blocks[1]["text"].startswith("Oh my god")

def test_weak_punct_does_not_beat_strong_sentence_end():
    # "Hey," ends with a comma — a weak punct. The boundary lands right after
    # it, but the strong "god." end must win so "Hey," stays with speaker B.
    segments = [_seg(
        " No, I... oh god. Hey, what's one thing? Um, I work security.",
        0.0, 10.0,
        [_w(" No,", 0.0, 0.6), _w(" I...", 0.7, 1.2), _w(" oh", 1.3, 1.7),
         _w(" god.", 1.8, 2.3), _w(" Hey,", 2.35, 2.7), _w(" what's", 2.75, 3.2),
         _w(" one", 3.25, 3.5), _w(" thing?", 3.55, 4.0), _w(" Um,", 4.1, 4.5),
         _w(" I", 4.55, 4.8), _w(" work", 4.85, 5.2), _w(" security.", 5.25, 6.0)],
    )]
    blocks = split_text_by_speaker(
        segments, [(0.0, 2.8, "A"), (2.8, 10.0, "B")], min_turn_s=0.5,
        boundary_shift_s=0.15, boundary_snap_s=0.35,
    )
    assert len(blocks) == 2
    assert blocks[0]["text"].endswith("god.")
    assert blocks[1]["text"].startswith("Hey,")
