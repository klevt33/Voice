# transcription_strategies.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Tuple
import logging
import os
import time
import io
import re
import requests
from datetime import datetime
from audio_handler import AudioSegment

# Configure logger for this module
logger = logging.getLogger(__name__)

# Minimum number of echoed words required before a stretch of text is treated as
# an echo of the Whisper initial prompt.  Three words or fewer are far too easy
# to hit by accident with genuine speech.
MIN_ECHO_WORDS = 4

# Number of echoed words after which a *partial* echo is trusted enough to strip
# from the front of an otherwise real utterance.  If fewer words echo, the
# overlap is assumed to be coincidental and the text is left untouched.
MIN_STRONG_ECHO_WORDS = 6

# Similarity ratio (0-1) required for two prompt-echo words to count as the same
# word.  This absorbs near-misses such as "capitalization" vs "capitalisation".
ECHO_WORD_SIMILARITY = 0.85

# How many near-miss words are tolerated inside a single echo run.  More than one
# means the text has genuinely diverged from the prompt.
MAX_ECHO_NEAR_MISSES = 1

# Minimum length for a truncated final word (e.g. prompt "...punctuation." echoed
# as "...punctua") to still count as an echo of that prompt word.
MIN_TRUNCATED_WORD_LEN = 3

# Whitespace and punctuation left dangling at the front of a text once a leading
# prompt echo has been cut off.
_LEADING_NOISE = " \t\r\n.,;:!?-–—\"'()[]…"

# Vocal fillers that carry no information.  An utterance made up of nothing but
# these (e.g. "Mh, mh, mh" — turbo loves inventing these on breath noise) is
# junk; a real sentence that merely contains one is not.
_FILLER_WORDS = frozenset({
    "mh", "mm", "mhm", "hm", "hmm", "uh", "um", "ah", "eh", "oh", "huh",
})

# Scripts that can never appear in genuine English output.  LANGUAGE is forced
# to "en", yet turbo still decodes noise into CJK/Hangul/Cyrillic garbage.
_FOREIGN_SCRIPT_RE = re.compile(
    "["
    "぀-ヿ"      # Hiragana + Katakana
    "㐀-䶿一-鿿豈-﫿"  # CJK ideographs (ext-A + unified + compat)
    "가-힯ᄀ-ᅟ"  # Hangul syllables + Jamo
    "Ѐ-ӿ"      # Cyrillic + supplement
    "؀-ۿݐ-ݿ"  # Arabic + supplement
    "ऀ-ॿ"      # Devanagari
    "]"
)

# A word (>= 2 chars) repeated verbatim 4+ times in a row — "clip clip clip
# clip" — is a decoding loop, not speech.
_CONSECUTIVE_WORD_REPEAT_RE = re.compile(
    r"\b(\w{2,})\b(?:[\s,.!?;:'\"()\-–—]+\1\b){3,}", re.IGNORECASE
)

# Texts with this many words or more whose unique-word ratio falls below
# _MIN_UNIQUE_WORD_RATIO are degenerate repetitions even when the repeats are
# not strictly consecutive ("Select the product. Select the product. ...").
_REPEAT_CHECK_MIN_WORDS = 6
_MIN_UNIQUE_WORD_RATIO = 0.45
_MIN_CONSECUTIVE_RUN = 4

# Whole-text junk prefixes, matched case-insensitively after punctuation removal.
JUNK_TEXT_PREFIXES = (
    "for more information visit",
    "amaraorg",
    "amara org",
)

# Bracketed sound markers Whisper emits on silence, e.g. "[MUSIC]" or "(applause)".
_SOUND_MARKER_RE = re.compile(r"^[\[\(\*]{1,2}\s*[^)\]\n]{1,40}\s*[\]\)\*]{1,2}[.!?]?$")
_MUSIC_NOTE_RE = re.compile(r"^[\s\u2669\u266a\u266b\u266c]+$")
_SOUND_MARKER_WORDS = (
    "music",
    "applause",
    "laughter",
    "laughing",
    "laugh",
    "silence",
    "inaudible",
    "sound",
    "noise",
    "upbeat",
    "background",
)


def _normalize_words(text: str) -> List[Tuple[str, int]]:
    """
    Split text into (word, end_offset) pairs, case-folded and free of punctuation.

    Working on words instead of raw substrings is what makes the prompt-echo
    check robust: Whisper re-punctuates, re-capitalises and re-spaces the prompt
    echo, so the characters rarely match the prompt exactly.

    Offsets index into the *original* string so the caller can slice the text
    at an exact word boundary.
    """
    return [(m.group(0).casefold(), m.end()) for m in re.finditer(r"\w+", text)]


def _words_match(a: str, b: str) -> bool:
    """True if two words are the same for echo-detection purposes."""
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    return SequenceMatcher(None, a, b).ratio() >= ECHO_WORD_SIMILARITY


def _is_truncated_word(text_word: str, prompt_word: str) -> bool:
    """True if one word is a truncated form of the other (>= 3 chars)."""
    if len(text_word) < MIN_TRUNCATED_WORD_LEN or len(prompt_word) < MIN_TRUNCATED_WORD_LEN:
        return False
    return text_word.startswith(prompt_word) or prompt_word.startswith(text_word)


def _echo_word_count(text_words: List[str], prompt_words: List[str]) -> int:
    """
    Count how many leading words of `text_words` echo the start of `prompt_words`.

    Matching tolerates:
    - case and punctuation differences (already normalised away),
    - a truncated final word (Whisper cut off mid-word),
    - up to MAX_ECHO_NEAR_MISSES near-miss words (e.g. spelling variants).
    """
    count = 0
    near_misses = 0
    for i in range(min(len(text_words), len(prompt_words))):
        text_word, prompt_word = text_words[i], prompt_words[i]
        if text_word == prompt_word:
            count += 1
            continue
        # A cut-off last word still means the model was echoing the prompt.
        if i == len(text_words) - 1 and _is_truncated_word(text_word, prompt_word):
            count += 1
            continue
        if near_misses < MAX_ECHO_NEAR_MISSES and _words_match(text_word, prompt_word):
            near_misses += 1
            count += 1
            continue
        break
    return count


def _is_prompt_fragment(text_words: List[str], prompt_words: List[str]) -> bool:
    """
    True if *every* word of the text comes from the initial prompt, in order.

    Whisper sometimes echoes only the tail of the prompt ("Use proper
    capitalization and punctuation.") as a segment of its own, which no
    prefix-based check can see.  Requiring every word to be a prompt word, in
    the same relative order, keeps real speech out: ordinary speech introduces
    words the prompt does not contain.
    """
    if len(text_words) < MIN_ECHO_WORDS or not prompt_words:
        return False
    position = 0
    for word in text_words:
        while position < len(prompt_words) and prompt_words[position] != word:
            position += 1
        if position == len(prompt_words):
            return False
        position += 1
    return True


def _strip_leading_prompt_echo(
    text: str, prompt_words: List[str], strong_echo_words: int
) -> Tuple[str, int]:
    """
    Remove a leading echo of the Whisper initial prompt from `text`.

    Returns (text_with_echo_removed, number_of_echoed_words).  When the whole
    utterance is an echo, the remainder is empty and the caller filters it out.
    A weak echo (fewer than `strong_echo_words` words) leaves the text unchanged
    so genuine speech is never truncated on a weak coincidence.
    """
    if not text or not prompt_words:
        return text, 0
    normalized = _normalize_words(text)
    if len(normalized) < MIN_ECHO_WORDS:
        return text, 0
    echo_words = _echo_word_count([w for w, _ in normalized], prompt_words)
    if echo_words < MIN_ECHO_WORDS:
        return text, 0
    remainder = text[normalized[echo_words - 1][1]:].lstrip(_LEADING_NOISE)
    if not remainder:
        return "", echo_words
    if echo_words < strong_echo_words:
        return text, 0
    return remainder, echo_words


def _is_sound_marker(text: str) -> bool:
    """True for bracketed non-speech markers such as "[MUSIC]" or "(applause)"."""
    stripped = text.strip()
    if _MUSIC_NOTE_RE.match(stripped):
        return True
    if not _SOUND_MARKER_RE.match(stripped):
        return False
    lt = stripped.casefold()
    return any(word in lt for word in _SOUND_MARKER_WORDS)


def _hotword_vocabulary() -> frozenset:
    """Normalised word set built from the configured Whisper hotwords.

    Turbo hallucinations on non-speech frequently echo the hotwords themselves
    ("Claude Claude", "Pooja", "Claude Code Sonnet"), so a text made up
    exclusively of hotwords is treated like an initial-prompt echo.
    """
    try:
        from config import WHISPER_HOTWORDS
    except Exception:
        return frozenset()
    words = set()
    for phrase in WHISPER_HOTWORDS or []:
        words.update(w for w, _ in _normalize_words(phrase))
    return frozenset(words)


def _is_filler_only(words: List[str]) -> bool:
    """True when every word is a vocal filler ("Mh, mh, mh", "Mm-mm-mm")."""
    return bool(words) and all(w in _FILLER_WORDS for w in words)


def _is_hotwords_only(words: List[str], hotword_words: frozenset) -> bool:
    """True when a >=2-word text is composed exclusively of hotwords."""
    return (
        len(words) >= 2
        and bool(hotword_words)
        and all(w in hotword_words for w in words)
    )


def _is_degenerate_repetition(text: str) -> bool:
    """True for decoding-loop output ("clip clip clip clip", repeated phrases)."""
    if _CONSECUTIVE_WORD_REPEAT_RE.search(text):
        return True
    words = [w for w, _ in _normalize_words(text)]
    if len(words) >= _REPEAT_CHECK_MIN_WORDS:
        return len(set(words)) / len(words) < _MIN_UNIQUE_WORD_RATIO
    return False


def _apply_text_junk_filter(
    text: str, hotword_words: frozenset = frozenset()
) -> str:
    """Apply the length- and phrase-based junk rules. Returns "" when filtered."""
    lt = text.casefold()
    if (
        ("thank" in lt or "subtitle" in lt or "captions" in lt)
        and len(text) <= 40
    ) or len(text) <= 10:
        return ""
    if lt.startswith("closed caption") and len(text) < 65:
        return ""
    if lt.startswith("transcription by"):
        return ""
    unpunctuated = re.sub(r"[^\w\s]", "", lt)
    if any(unpunctuated.startswith(prefix) for prefix in JUNK_TEXT_PREFIXES):
        return ""
    if _is_sound_marker(text):
        return ""
    if _FOREIGN_SCRIPT_RE.search(text):
        return ""
    words = [w for w, _ in _normalize_words(text)]
    if _is_filler_only(words) or _is_hotwords_only(words, hotword_words):
        return ""
    if _is_degenerate_repetition(text):
        return ""
    return text


def _fields_are_confident(
    no_speech_prob, avg_logprob, compression_ratio
) -> bool:
    """Confidence thresholds shared by faster-whisper and API segment metadata.

    Uses the same signals faster-whisper applies internally: a segment is
    non-speech when the model's no-speech score is high *and* its average log
    probability is low.  Additionally, very low log probability or a very high
    compression ratio alone mark a degenerate decode.  Missing values (None)
    never trigger a drop.
    """
    from config import (
        SEG_NO_SPEECH_PROB_DROP, SEG_NO_SPEECH_LOGPROB,
        SEG_MIN_AVG_LOGPROB, SEG_MAX_COMPRESSION_RATIO,
    )

    def _num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    no_speech_prob = _num(no_speech_prob)
    avg_logprob = _num(avg_logprob)
    compression_ratio = _num(compression_ratio)

    if (
        no_speech_prob is not None
        and avg_logprob is not None
        and no_speech_prob > SEG_NO_SPEECH_PROB_DROP
        and avg_logprob < SEG_NO_SPEECH_LOGPROB
    ):
        return False
    if avg_logprob is not None and avg_logprob < SEG_MIN_AVG_LOGPROB:
        return False
    if compression_ratio is not None and compression_ratio > SEG_MAX_COMPRESSION_RATIO:
        return False
    return True


def _segment_is_confident(segment) -> bool:
    """False when decoder metadata marks the segment as likely hallucination.

    Segments missing these attributes (test doubles, API responses without
    metadata) pass through.
    """
    return _fields_are_confident(
        getattr(segment, "no_speech_prob", None),
        getattr(segment, "avg_logprob", None),
        getattr(segment, "compression_ratio", None),
    )


def _seg_field(segment, name):
    """Read a field from a segment whether it is a dict or an attribute object."""
    if isinstance(segment, dict):
        return segment.get(name)
    return getattr(segment, name, None)


def _prompt_echo_config(initial_prompt: str | None) -> Tuple[List[str], int]:
    """
    Pre-compute the normalised prompt words and the strong-echo threshold.

    The threshold is capped by the prompt length so a short custom prompt still
    gets the prefix-stripping behaviour instead of being permanently unstrippable.
    """
    prompt_words = [word for word, _ in _normalize_words(initial_prompt or "")]
    return prompt_words, min(MIN_STRONG_ECHO_WORDS, len(prompt_words))


def apply_hallucination_filter(text: str, initial_prompt: str | None = None) -> str:
    """
    Filter out likely hallucinations or junk from transcription output.

    Removes text that matches known whisper hallucination patterns:
    - Short phrases containing "thank", "subtitles", or "captions" (≤ 40 chars)
    - Any result of 10 characters or fewer
    - Text starting with "closed caption" and shorter than 65 chars
    - Text starting with "transcription by" (case-insensitive)
    - Text starting with "for more information visit" or "amara.org" (after
      lowercasing and stripping punctuation)
    - Bracketed sound markers such as "[MUSIC]" or "(applause)"
    - Any leading echo of the Whisper initial prompt that is at least
      MIN_ECHO_WORDS words long.  Comparison is word-based, so it survives
      re-capitalisation, re-punctuation, missing spaces, a truncated final word
      and near-miss spellings.  An echo covering the whole utterance is dropped;
      a strong echo followed by real speech has the echo stripped and the real
      speech is re-checked by the remaining rules.

    Returns the original text if it passes, or "" if filtered.
    """
    prompt_words, strong_echo_words = _prompt_echo_config(initial_prompt)

    if prompt_words:
        if not text:
            return ""
        while text:
            remainder, echo_words = _strip_leading_prompt_echo(
                text, prompt_words, strong_echo_words
            )
            if not echo_words:
                break
            if not remainder:
                # The entire utterance was the prompt echo.
                return ""
            text = remainder
        # A prompt echo that is not a prefix of the prompt (Whisper echoing only
        # its tail) is caught here, but only when nothing else was said.
        if _is_prompt_fragment([w for w, _ in _normalize_words(text)], prompt_words):
            return ""

    return _apply_text_junk_filter(text, _hotword_vocabulary())


def process_whisper_segments(segments, initial_prompt: str | None = None) -> str:
    """
    Join faster-whisper segment objects into a single cleaned, filtered string.

    Echoed prompt segments are dropped individually before joining, so a prompt
    echo that Whisper emitted as its own segment does not poison the joined text
    that the whole-utterance rules below run against.  Segment texts are then
    joined, extra whitespace is collapsed, and the hallucination filter is
    applied.  Returns an empty string for empty/filtered results.
    """
    segment_list = list(segments)
    if not segment_list:
        return ""
    prompt_words, strong_echo_words = _prompt_echo_config(initial_prompt)
    kept: List[str] = []
    for segment in segment_list:
        if not _segment_is_confident(segment):
            logger.debug(
                "Dropped low-confidence segment "
                f"(no_speech={getattr(segment, 'no_speech_prob', None)}, "
                f"avg_logprob={getattr(segment, 'avg_logprob', None)}, "
                f"compression={getattr(segment, 'compression_ratio', None)}): "
                f"{(segment.text or '')[:60]!r}"
            )
            continue
        segment_text = segment.text or ""
        if prompt_words:
            remainder, echo_words = _strip_leading_prompt_echo(
                segment_text, prompt_words, strong_echo_words
            )
            if echo_words:
                if not remainder:
                    # The segment was nothing but the prompt echo.
                    continue
                segment_text = remainder
            elif _is_prompt_fragment(
                [w for w, _ in _normalize_words(segment_text)], prompt_words
            ):
                # The segment echoes part of the prompt that is not a prefix of
                # it, so the prefix-based strip cannot see it.
                continue
        kept.append(segment_text)
    transcript_text = " ".join(kept)
    cleaned_text = re.sub(r" {2,}", " ", transcript_text.strip())
    return apply_hallucination_filter(cleaned_text, initial_prompt)


@dataclass
class TranscriptionResult:
    """Result of a transcription operation"""
    text: str
    method_used: str  # "local_gpu", "groq_api"
    processing_time: float
    fallback_used: bool
    error_message: Optional[str] = None
    timestamp: datetime = None
    # Optional structured output: [{start, end, text, words: [{start, end, word}]}]
    # used by client-side speaker splitting on the OTHERS channel.
    segments: Optional[List[Dict[str, Any]]] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class StrategyConfig:
    """Configuration for a transcription strategy"""
    name: str
    enabled: bool
    priority: int
    timeout: float
    retry_count: int
    specific_config: Dict[str, Any]

class TranscriptionStrategy(ABC):
    """Abstract base class for transcription strategies"""
    
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._last_error = None
        self._error_count = 0
        self._last_success_time = None
    
    @abstractmethod
    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """
        Transcribe audio segment and return result
        
        Args:
            audio_segment: AudioSegment object containing audio data
            
        Returns:
            TranscriptionResult with transcription text and metadata
            
        Raises:
            TranscriptionError: If transcription fails
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if transcription method is available
        
        Returns:
            True if the strategy can be used, False otherwise
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """
        Get strategy name for logging/UI
        
        Returns:
            Human-readable name of the strategy
        """
        pass
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status of the strategy
        
        Returns:
            Dictionary with health information
        """
        return {
            "name": self.get_name(),
            "available": self.is_available(),
            "enabled": self.config.enabled,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "last_success_time": self._last_success_time
        }
    
    def _record_success(self):
        """Record a successful transcription"""
        self._last_success_time = datetime.now()
        self._error_count = 0
        self._last_error = None
    
    def _record_error(self, error: Exception):
        """Record a transcription error"""
        self._error_count += 1
        self._last_error = str(error)
        self.logger.error(f"Transcription error in {self.get_name()}: {error}")
    
    def cleanup(self):
        """
        Cleanup resources used by the strategy
        Override in subclasses if needed
        """
        pass

class TranscriptionError(Exception):
    """Exception raised when transcription fails"""
    
    def __init__(self, message: str, strategy_name: str, original_error: Exception = None):
        self.message = message
        self.strategy_name = strategy_name
        self.original_error = original_error
        super().__init__(f"[{strategy_name}] {message}")


class LocalGPUTranscriptionStrategy(TranscriptionStrategy):
    """Local GPU transcription strategy using faster-whisper"""
    
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self._model = None
        self._device = None
        # Detect device at construction time (cheap), but don't load the model yet
        self._detect_device()

    def _detect_device(self):
        """Detect the target device without loading the model."""
        try:
            import torch
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            self._device = "cpu"

    def load_model(self):
        """Load the faster-whisper model into memory (GPU/CPU). No-op if already loaded."""
        if self._model is not None:
            return

        try:
            try:
                import torch
            except ImportError:
                raise TranscriptionError("PyTorch not available", self.get_name())

            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise TranscriptionError("faster-whisper not available", self.get_name())

            from config import WHISPER_MODEL, COMPUTE_TYPE, MODELS_FOLDER

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self.logger.info(f"Loading faster-whisper model on {self._device}...")

            if not os.path.exists(MODELS_FOLDER):
                os.makedirs(MODELS_FOLDER)

            compute_type = COMPUTE_TYPE if self._device == "cuda" else "int8"
            self._model = WhisperModel(
                WHISPER_MODEL,
                device=self._device,
                compute_type=compute_type,
                download_root=MODELS_FOLDER,
            )
            self.logger.info(f"faster-whisper model loaded successfully on {self._device}")

        except Exception as e:
            self.logger.error(f"Error loading faster-whisper model: {e}")
            self._record_error(e)
            raise TranscriptionError(f"Failed to load local GPU model: {e}", self.get_name(), e)

    def unload_model(self):
        """Unload the model and free GPU/CPU memory."""
        if self._model is None:
            return
        try:
            del self._model
            self._model = None
            if self._device == "cuda":
                try:
                    import torch
                    import gc
                    gc.collect()
                    torch.cuda.empty_cache()
                    self.logger.debug("CUDA cache cleared after model unload")
                except ImportError:
                    pass
            self.logger.info("faster-whisper model unloaded")
        except Exception as e:
            self.logger.warning(f"Error unloading model: {e}")
    
    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """Transcribe audio using local faster-whisper model (loads model on first call)."""
        start_time = time.time()

        try:
            # Load model on demand if not already loaded
            self.load_model()
        except TranscriptionError as e:
            return TranscriptionResult(
                text="",
                method_used="local_gpu",
                processing_time=time.time() - start_time,
                fallback_used=False,
                error_message=str(e),
            )

        try:
            from config import (
                LANGUAGE, BEAM_SIZE, WHISPER_HOTWORDS, WHISPER_INITIAL_PROMPT,
                WHISPER_VAD_ENABLED, WHISPER_VAD_PARAMETERS,
                WHISPER_CONDITION_ON_PREV_TEXT, WHISPER_REPETITION_PENALTY,
                WHISPER_NO_REPEAT_NGRAM_SIZE, WHISPER_WORD_TIMESTAMPS,
                SPEAKER_SPLIT_ENABLED,
            )

            audio_data = audio_segment.get_wav_bytes()
            if not audio_data:
                raise TranscriptionError("Could not get WAV data from audio segment", self.get_name())

            # Speaker splitting needs word timings even if not explicitly requested.
            word_timestamps = WHISPER_WORD_TIMESTAMPS or SPEAKER_SPLIT_ENABLED

            hotwords_str = " ".join(WHISPER_HOTWORDS) if WHISPER_HOTWORDS else None
            initial_prompt = WHISPER_INITIAL_PROMPT if WHISPER_INITIAL_PROMPT else None
            self.logger.debug(
                f"Transcribing with hotwords={'%d words' % len(WHISPER_HOTWORDS) if WHISPER_HOTWORDS else 'disabled'}, "
                f"initial_prompt={'set' if initial_prompt else 'disabled'}, "
                f"vad={'on' if WHISPER_VAD_ENABLED else 'off'}"
            )

            with io.BytesIO(audio_data) as audio_io:
                segments, info = self._model.transcribe(
                    audio_io,
                    language=LANGUAGE,
                    beam_size=BEAM_SIZE,
                    word_timestamps=word_timestamps,
                    hotwords=hotwords_str,
                    initial_prompt=initial_prompt,
                    vad_filter=WHISPER_VAD_ENABLED,
                    vad_parameters=WHISPER_VAD_PARAMETERS if WHISPER_VAD_ENABLED else None,
                    condition_on_previous_text=WHISPER_CONDITION_ON_PREV_TEXT,
                    repetition_penalty=WHISPER_REPETITION_PENALTY,
                    no_repeat_ngram_size=WHISPER_NO_REPEAT_NGRAM_SIZE,
                )
                segment_list = list(segments)
                result_text = process_whisper_segments(segment_list, initial_prompt)
                if not result_text:
                    self.logger.info("Filtered out likely hallucination from local GPU transcription")

            response_segments = [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "words": (
                        [
                            {"start": w.start, "end": w.end, "word": w.word}
                            for w in (seg.words or [])
                        ]
                        if word_timestamps
                        else []
                    ),
                }
                for seg in segment_list
            ]

            processing_time = time.time() - start_time
            self._record_success()

            return TranscriptionResult(
                text=result_text,
                method_used="local_gpu",
                processing_time=processing_time,
                fallback_used=False,
                segments=response_segments,
            )

        except Exception as e:
            self._record_error(e)
            return TranscriptionResult(
                text="",
                method_used="local_gpu",
                processing_time=time.time() - start_time,
                fallback_used=False,
                error_message=str(e),
            )

    def is_available(self) -> bool:
        """Return True if the dependencies are installed (model need not be loaded yet)."""
        try:
            import torch
            from faster_whisper import WhisperModel
            return True
        except ImportError:
            return False

    def is_model_loaded(self) -> bool:
        """Return True if the model is currently loaded in memory."""
        return self._model is not None
    
    def get_name(self) -> str:
        """Get strategy name"""
        return f"Local GPU ({self._device.upper()})" if self._device else "Local GPU"
    
    def cleanup(self):
        """Cleanup GPU resources."""
        self.unload_model()
        self.logger.info("Local GPU transcription resources cleaned up")


class GroqAPITranscriptionStrategy(TranscriptionStrategy):
    """Groq API transcription strategy using cloud-based Whisper"""
    
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self._client = None
        self._api_key = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Groq API client"""
        try:
            from config import get_groq_api_key, GROQ_MODEL
            
            self._api_key = get_groq_api_key()
            if not self._api_key:
                self.logger.warning("Groq API key not found in environment variables")
                return
            
            # Import Groq client
            try:
                from groq import Groq
                self._client = Groq(api_key=self._api_key)
                self.logger.info("Groq API client initialized successfully")
            except ImportError as e:
                self.logger.error("Groq package not installed. Install with: pip install groq")
                raise TranscriptionError("Groq package not available", self.get_name(), e)
                
        except Exception as e:
            self.logger.error(f"Error initializing Groq API client: {e}")
            self._record_error(e)
    
    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """Transcribe audio using Groq API with retry logic"""
        if not self.is_available():
            raise TranscriptionError("Groq API transcription not available", self.get_name())
        
        start_time = time.time()
        
        # Validate audio for API compatibility
        is_valid, validation_error = audio_segment.is_valid_for_api()
        if not is_valid:
            return TranscriptionResult(
                text="",
                method_used="groq_api",
                processing_time=time.time() - start_time,
                fallback_used=False,
                error_message=f"Audio validation failed: {validation_error}"
            )
        
        # Attempt transcription with retry logic
        return self._transcribe_with_retry(audio_segment, start_time)
    
    def _transcribe_with_retry(self, audio_segment: AudioSegment, start_time: float) -> TranscriptionResult:
        """Perform transcription with exponential backoff retry"""
        from config import API_RETRY_COUNT, API_RETRY_BACKOFF, GROQ_MODEL
        import time as time_module
        
        last_error = None
        
        for attempt in range(API_RETRY_COUNT + 1):  # +1 for initial attempt
            try:
                # Get API-compatible audio data
                audio_data = audio_segment.get_api_compatible_wav_bytes()
                if not audio_data:
                    raise TranscriptionError("Could not get API-compatible WAV data", self.get_name())
                
                audio_size_mb = len(audio_data) / (1024 * 1024)
                self.logger.debug(f"Attempt {attempt + 1}: Sending {audio_size_mb:.2f}MB audio to Groq API...")
                
                # Create transcription request with timeout handling
                transcription = self._make_api_request(audio_data, GROQ_MODEL)
                
                # Extract and process text + structured segments
                result_text, response_segments = self._process_transcription_response(transcription)
                
                processing_time = time_module.time() - start_time
                self._record_success()
                
                self.logger.info(f"Groq API transcription completed in {processing_time:.2f}s (attempt {attempt + 1})")
                
                return TranscriptionResult(
                    text=result_text,
                    method_used="groq_api",
                    processing_time=processing_time,
                    fallback_used=False,
                    segments=response_segments,
                )
                
            except Exception as e:
                last_error = e
                error_type = self._categorize_error(e)
                
                # Don't retry for certain error types
                if error_type in ["authentication_error", "validation_error"]:
                    self.logger.error(f"Non-retryable error: {error_type} - {e}")
                    break
                
                # Log retry attempt
                if attempt < API_RETRY_COUNT:
                    backoff_time = API_RETRY_BACKOFF ** attempt
                    self.logger.warning(f"API request failed (attempt {attempt + 1}), retrying in {backoff_time:.1f}s: {e}")
                    time_module.sleep(backoff_time)
                else:
                    self.logger.error(f"API request failed after {API_RETRY_COUNT + 1} attempts: {e}")
        
        # All attempts failed
        self._record_error(last_error)
        processing_time = time_module.time() - start_time
        error_type = self._categorize_error(last_error)
        
        return TranscriptionResult(
            text="",
            method_used="groq_api",
            processing_time=processing_time,
            fallback_used=False,
            error_message=f"{error_type}: {last_error}"
        )
    
    def _make_api_request(self, audio_data: bytes, model: str):
        """Make API request with timeout handling"""
        from config import (
            API_REQUEST_TIMEOUT, WHISPER_WORD_TIMESTAMPS, SPEAKER_SPLIT_ENABLED,
        )
        import signal

        # Speaker splitting needs word timings even if not explicitly requested.
        granularities = ["segment"]
        if WHISPER_WORD_TIMESTAMPS or SPEAKER_SPLIT_ENABLED:
            granularities.append("word")

        def create():
            return self._client.audio.transcriptions.create(
                file=("audio.wav", audio_data),
                model=model,
                response_format="verbose_json",
                language="en",
                timestamp_granularities=granularities,
            )

        def timeout_handler(signum, frame):
            raise TimeoutError(f"API request timed out after {API_REQUEST_TIMEOUT}s")

        # Set up timeout (Unix-like systems)
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(API_REQUEST_TIMEOUT))

            try:
                return create()
            finally:
                signal.alarm(0)  # Cancel the alarm
                signal.signal(signal.SIGALRM, old_handler)

        except (AttributeError, OSError):
            # Windows or signal not available, use basic request without timeout signal
            # The Groq client should have its own timeout handling
            return create()

    def _process_transcription_response(self, transcription) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """Process and filter transcription response.

        Returns (filtered_text, structured_segments).  Per-segment confidence
        metadata (avg_logprob / compression_ratio / no_speech_prob) is applied
        before joining so junk decodes never reach the text-level filter.
        """
        api_segments = getattr(transcription, "segments", None) or []
        api_words = getattr(transcription, "words", None) or []

        kept_texts: List[str] = []
        response_segments: List[Dict[str, Any]] = []
        for seg in api_segments:
            if not _fields_are_confident(
                _seg_field(seg, "no_speech_prob"),
                _seg_field(seg, "avg_logprob"),
                _seg_field(seg, "compression_ratio"),
            ):
                self.logger.debug(
                    "Dropped low-confidence Groq segment: "
                    f"{(_seg_field(seg, 'text') or '')[:60]!r}"
                )
                continue
            kept_texts.append(_seg_field(seg, "text") or "")
            response_segments.append(
                {
                    "start": _seg_field(seg, "start"),
                    "end": _seg_field(seg, "end"),
                    "text": _seg_field(seg, "text") or "",
                    "words": self._words_in_range(
                        api_words,
                        _seg_field(seg, "start"),
                        _seg_field(seg, "end"),
                    ),
                }
            )

        if api_segments:
            result_text = " ".join(t for t in kept_texts if t).strip()
        else:
            result_text = transcription.text.strip() if transcription.text else ""

        if result_text:
            # Replace multiple consecutive spaces with a single space
            result_text = re.sub(r' {2,}', ' ', result_text)
            from config import WHISPER_INITIAL_PROMPT
            filtered = apply_hallucination_filter(result_text, WHISPER_INITIAL_PROMPT)
            if not filtered:
                self.logger.info(f"Filtered out likely hallucination: {result_text}")
                # Everything filtered — drop the structured segments too.
                response_segments = []
            result_text = filtered

        return result_text, response_segments or None

    @staticmethod
    def _words_in_range(words, start, end) -> List[Dict[str, Any]]:
        """Group top-level word timestamps into the segment that contains them."""
        grouped = []
        for w in words:
            w_start = _seg_field(w, "start")
            if w_start is None or start is None or end is None:
                continue
            if start <= w_start <= end:
                grouped.append(
                    {
                        "start": w_start,
                        "end": _seg_field(w, "end"),
                        "word": _seg_field(w, "word") or "",
                    }
                )
        return grouped
    
    def _categorize_error(self, error: Exception) -> str:
        """Categorize API errors for appropriate handling"""
        error_message = str(error).lower()
        
        if "authentication" in error_message or "api key" in error_message or "unauthorized" in error_message:
            return "authentication_error"
        elif "rate limit" in error_message or "quota" in error_message or "too many requests" in error_message:
            return "rate_limit_error"
        elif "timeout" in error_message or "connection" in error_message or "network" in error_message:
            return "network_error"
        elif "validation" in error_message or "invalid" in error_message:
            return "validation_error"
        else:
            return "api_error"
    
    def is_available(self) -> bool:
        """Check if Groq API transcription is available"""
        try:
            from config import is_groq_api_available
            return self._client is not None and is_groq_api_available()
        except ImportError:
            return False
    
    def get_name(self) -> str:
        """Get strategy name"""
        return "Groq API"
    
    def _validate_api_key(self) -> bool:
        """Validate API key by making a test request (optional)"""
        # This could be implemented to test the API key validity
        # For now, we just check if the key exists
        return self._api_key is not None and len(self._api_key.strip()) > 0
    
    def cleanup(self):
        """Cleanup API resources"""
        try:
            if self._client:
                # Close any open connections (if the client supports it)
                self._client = None
            
            self._api_key = None
            self.logger.info("Groq API transcription resources cleaned up")
        except Exception as e:
            self.logger.warning(f"Error during API cleanup: {e}")


class NetworkGPUTranscriptionStrategy(TranscriptionStrategy):
    """Network GPU transcription strategy — sends WAV bytes to a remote HTTP server"""

    AVAILABILITY_CACHE_TTL = 10.0

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self._availability_cache: Optional[bool] = None
        self._availability_cache_time: Optional[float] = None
        # Allow specific_config to override the global NETWORK_GPU_SERVER_URL.
        # This is used by the ModelService integration to point to port 8766
        # instead of the default NETWORK_GPU_SERVER_URL (port 8765).
        self._server_url_override: Optional[str] = config.specific_config.get("server_url")

    def _get_server_url(self) -> str:
        """Return the effective server URL (override takes precedence over config)."""
        if self._server_url_override:
            return self._server_url_override
        from config import NETWORK_GPU_SERVER_URL
        return NETWORK_GPU_SERVER_URL

    def get_name(self) -> str:
        """Get strategy name"""
        return "Network GPU"

    def is_available(self) -> bool:
        """Check server health with a 10-second cache"""
        now = time.monotonic()
        if (
            self._availability_cache is not None
            and self._availability_cache_time is not None
            and (now - self._availability_cache_time) < self.AVAILABILITY_CACHE_TTL
        ):
            return self._availability_cache

        try:
            server_url = self._get_server_url()
            response = requests.get(
                f"{server_url}/health",
                timeout=3.0
            )
            result = (
                response.status_code == 200
                and response.json().get("status") == "ok"
            )
        except Exception:
            result = False

        self._availability_cache = result
        self._availability_cache_time = time.monotonic()
        return result

    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """Send WAV bytes to the network GPU server and return a TranscriptionResult"""
        from config import NETWORK_GPU_TIMEOUT, NETWORK_GPU_API_KEY

        server_url = self._get_server_url()
        start_time = time.time()

        try:
            from config import WHISPER_WORD_TIMESTAMPS, SPEAKER_SPLIT_ENABLED

            wav_bytes = audio_segment.get_wav_bytes()

            headers = {"Content-Type": "application/octet-stream"}
            if NETWORK_GPU_API_KEY:
                headers["Authorization"] = f"Bearer {NETWORK_GPU_API_KEY}"

            # Ask the server for word timings when this client splits speakers —
            # works regardless of the server's own config.
            url = f"{server_url}/transcribe"
            if WHISPER_WORD_TIMESTAMPS or SPEAKER_SPLIT_ENABLED:
                url += "?word_timestamps=true"

            response = requests.post(
                url,
                data=wav_bytes,
                headers=headers,
                timeout=NETWORK_GPU_TIMEOUT
            )

            processing_time = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                self._record_success()
                return TranscriptionResult(
                    text=data.get("text", ""),
                    method_used="network_gpu",
                    processing_time=processing_time,
                    fallback_used=False,
                    segments=data.get("segments"),
                )
            else:
                error_message = f"HTTP {response.status_code}: {response.text}"
                self._record_error(Exception(error_message))
                return TranscriptionResult(
                    text="",
                    method_used="network_gpu",
                    processing_time=processing_time,
                    fallback_used=False,
                    error_message=error_message
                )

        except (requests.ConnectionError, requests.Timeout) as e:
            processing_time = time.time() - start_time
            error_message = f"Connection failed: {e}"
            self._record_error(e)
            return TranscriptionResult(
                text="",
                method_used="network_gpu",
                processing_time=processing_time,
                fallback_used=False,
                error_message=error_message
            )
        except Exception as e:
            processing_time = time.time() - start_time
            error_message = f"Unexpected error: {e}"
            self._record_error(e)
            return TranscriptionResult(
                text="",
                method_used="network_gpu",
                processing_time=processing_time,
                fallback_used=False,
                error_message=error_message
            )


class ModelServiceTranscriptionStrategy(NetworkGPUTranscriptionStrategy):
    """Transcription strategy that delegates to the shared ModelService subprocess.

    Functionally identical to NetworkGPUTranscriptionStrategy but reports itself
    as "Local GPU (Shared)" so the UI correctly identifies it as a local GPU mode
    rather than a remote network GPU server.
    """

    def get_name(self) -> str:
        return "Local GPU (Shared)"


class TranscriptionManager:
    """Manages transcription strategies and handles fallback logic"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.TranscriptionManager")
        self._strategies = {}
        self._primary_strategy = None
        self._fallback_strategy = None
        self._current_strategy_name = None
        self._fallback_counts = {}
        self._last_fallback_time = {}
        self._strategy_lock = None
        self._performance_stats = {}
        self._initialize_lock()
        self._initialize_performance_tracking()
    
    def _initialize_lock(self):
        """Initialize thread lock for strategy switching"""
        try:
            import threading
            self._strategy_lock = threading.RLock()
        except ImportError:
            self.logger.warning("Threading not available, strategy switching may not be thread-safe")
    
    def _initialize_performance_tracking(self):
        """Initialize performance tracking data structures"""
        self._performance_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "fallback_requests": 0,
            "total_processing_time": 0.0,
            "strategy_stats": {},
            "recent_performance": []  # Last 100 requests for moving averages
        }
    
    def register_strategy(self, strategy: TranscriptionStrategy):
        """Register a transcription strategy"""
        strategy_name = strategy.get_name()
        self._strategies[strategy_name] = strategy
        self._fallback_counts[strategy_name] = 0
        self._last_fallback_time[strategy_name] = None
        self.logger.info(f"Registered transcription strategy: {strategy_name}")
    
    def set_primary_strategy(self, strategy_name: str) -> bool:
        """
        Set the primary transcription strategy
        
        Args:
            strategy_name: Name of the strategy to set as primary
            
        Returns:
            True if successful, False otherwise
        """
        if self._strategy_lock:
            with self._strategy_lock:
                return self._set_primary_strategy_unsafe(strategy_name)
        else:
            return self._set_primary_strategy_unsafe(strategy_name)
    
    def _set_primary_strategy_unsafe(self, strategy_name: str) -> bool:
        """Set primary strategy without locking (internal use)"""
        if strategy_name not in self._strategies:
            self.logger.error(f"Strategy not found: {strategy_name}")
            return False
        
        strategy = self._strategies[strategy_name]
        if not strategy.is_available():
            self.logger.warning(f"Strategy not available: {strategy_name}")
            return False
        
        self._primary_strategy = strategy
        self._current_strategy_name = strategy_name
        self.logger.info(f"Primary transcription strategy set to: {strategy_name}")
        return True
    
    def set_fallback_strategy(self, strategy_name: str) -> bool:
        """
        Set the fallback transcription strategy
        
        Args:
            strategy_name: Name of the strategy to set as fallback
            
        Returns:
            True if successful, False otherwise
        """
        if strategy_name not in self._strategies:
            self.logger.error(f"Fallback strategy not found: {strategy_name}")
            return False
        
        strategy = self._strategies[strategy_name]
        if not strategy.is_available():
            self.logger.warning(f"Fallback strategy not available: {strategy_name}")
            return False
        
        self._fallback_strategy = strategy
        self.logger.info(f"Fallback transcription strategy set to: {strategy_name}")
        return True
    
    def switch_strategy(self, new_strategy_name: str) -> bool:
        """
        Switch to a new primary strategy
        
        Args:
            new_strategy_name: Name of the new strategy
            
        Returns:
            True if successful, False otherwise
        """
        if self._strategy_lock:
            with self._strategy_lock:
                return self._switch_strategy_unsafe(new_strategy_name)
        else:
            return self._switch_strategy_unsafe(new_strategy_name)
    
    def _switch_strategy_unsafe(self, new_strategy_name: str) -> bool:
        """Switch strategy without locking (internal use)"""
        old_strategy_name = self._current_strategy_name
        old_strategy = self._primary_strategy

        if self._set_primary_strategy_unsafe(new_strategy_name):
            self.logger.info(f"Switched transcription strategy from {old_strategy_name} to {new_strategy_name}")

            # Unload local GPU model when switching away from it
            if old_strategy is not None and isinstance(old_strategy, LocalGPUTranscriptionStrategy):
                if new_strategy_name != old_strategy_name:
                    self.logger.info("Unloading local GPU model (no longer the active strategy)")
                    old_strategy.unload_model()

            # Load local GPU model when switching to it
            new_strategy = self._strategies.get(new_strategy_name)
            if isinstance(new_strategy, LocalGPUTranscriptionStrategy):
                self.logger.info("Loading local GPU model (now the active strategy)")
                try:
                    new_strategy.load_model()
                except Exception as e:
                    self.logger.error(f"Failed to load local GPU model on switch: {e}")
                    return False

            return True
        else:
            self.logger.error(f"Failed to switch to strategy: {new_strategy_name}")
            return False
    
    def transcribe_with_fallback(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """
        Transcribe audio with automatic fallback on failure
        
        Args:
            audio_segment: AudioSegment to transcribe
            
        Returns:
            TranscriptionResult with transcription and metadata
        """
        if not self._primary_strategy:
            raise TranscriptionError("No primary transcription strategy configured", "TranscriptionManager")
        
        start_time = time.time()
        
        # Try primary strategy first
        try:
            result = self._primary_strategy.transcribe(audio_segment)
            
            # Update performance stats
            self._update_performance_stats(result, start_time)
            
            # Check if transcription was successful
            if result.error_message is None and result.text:
                return result
            elif result.error_message is None:
                # Empty result but no error - this is valid (silence)
                return result
            else:
                # Primary strategy failed, try fallback
                self.logger.warning(f"Primary strategy failed: {result.error_message}")
                fallback_result = self._attempt_fallback(audio_segment, result)
                
                # Update performance stats for fallback
                if fallback_result.fallback_used:
                    self._update_performance_stats(fallback_result, start_time, is_fallback=True)
                
                return fallback_result
                
        except Exception as e:
            self.logger.error(f"Primary strategy exception: {e}")
            # Create error result and attempt fallback
            error_result = TranscriptionResult(
                text="",
                method_used=self._primary_strategy.get_name(),
                processing_time=time.time() - start_time,
                fallback_used=False,
                error_message=str(e)
            )
            
            # Update performance stats for error
            self._update_performance_stats(error_result, start_time)
            
            fallback_result = self._attempt_fallback(audio_segment, error_result)
            
            # Update performance stats for fallback
            if fallback_result.fallback_used:
                self._update_performance_stats(fallback_result, start_time, is_fallback=True)
            
            return fallback_result
    
    def _attempt_fallback(self, audio_segment: AudioSegment, primary_result: TranscriptionResult) -> TranscriptionResult:
        """Attempt fallback transcription"""
        from config import ENABLE_FALLBACK, FALLBACK_RETRY_LIMIT, FALLBACK_COOLDOWN_PERIOD
        
        if not ENABLE_FALLBACK or not self._fallback_strategy:
            self.logger.info("Fallback disabled or not configured")
            return primary_result
        
        fallback_name = self._fallback_strategy.get_name()
        primary_name = self._primary_strategy.get_name() if self._primary_strategy else "Unknown"
        
        # Check fallback retry limits
        if self._fallback_counts[fallback_name] >= FALLBACK_RETRY_LIMIT:
            last_fallback = self._last_fallback_time[fallback_name]
            if last_fallback:
                time_since_last = (datetime.now() - last_fallback).total_seconds()
                if time_since_last < FALLBACK_COOLDOWN_PERIOD:
                    self.logger.info(f"Fallback cooldown active for {fallback_name}")
                    return primary_result
                else:
                    # Reset fallback count after cooldown
                    self._fallback_counts[fallback_name] = 0
        
        try:
            self.logger.info(f"Attempting fallback transcription with {fallback_name}")
            
            # Notify about fallback activation
            self._notify_fallback_activation(primary_name, fallback_name, primary_result.error_message)
            
            fallback_result = self._fallback_strategy.transcribe(audio_segment)
            
            # Mark as fallback and update counters
            fallback_result.fallback_used = True
            self._fallback_counts[fallback_name] += 1
            self._last_fallback_time[fallback_name] = datetime.now()
            
            if fallback_result.error_message is None:
                self.logger.info(f"Fallback transcription successful with {fallback_name}")
                return fallback_result
            else:
                self.logger.warning(f"Fallback transcription also failed: {fallback_result.error_message}")
                return primary_result  # Return original error
                
        except Exception as e:
            self.logger.error(f"Fallback strategy exception: {e}")
            return primary_result  # Return original error
    
    def _notify_fallback_activation(self, from_method: str, to_method: str, reason: str):
        """Notify about fallback activation using exception notifier"""
        try:
            # Try to get exception notifier (it might not be available in all contexts)
            from exception_notifier import ExceptionNotifier
            notifier = ExceptionNotifier()
            notifier.notify_transcription_fallback(from_method, to_method, reason)
        except Exception as e:
            self.logger.debug(f"Could not notify fallback activation: {e}")
            # Don't fail the transcription process if notification fails
    
    def get_available_strategies(self) -> Dict[str, bool]:
        """Get list of available strategies"""
        return {name: strategy.is_available() for name, strategy in self._strategies.items()}
    
    def get_current_strategy_name(self) -> Optional[str]:
        """Get name of current primary strategy"""
        return self._current_strategy_name
    
    def get_strategy_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status of all strategies"""
        return {name: strategy.get_health_status() for name, strategy in self._strategies.items()}
    
    def cleanup(self):
        """Cleanup all strategies and manager resources"""
        try:
            # Cleanup all strategies
            for strategy in self._strategies.values():
                try:
                    strategy.cleanup()
                except Exception as e:
                    self.logger.warning(f"Error cleaning up strategy {strategy.get_name()}: {e}")
            
            # Clear strategy references
            self._strategies.clear()
            self._primary_strategy = None
            self._fallback_strategy = None
            self._current_strategy_name = None
            
            # Clear performance data to free memory
            self._performance_stats.clear()
            self._fallback_counts.clear()
            self._last_fallback_time.clear()
            
            # Force garbage collection
            import gc
            gc.collect()
            
            self.logger.info("TranscriptionManager cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during TranscriptionManager cleanup: {e}")
    
    def optimize_memory_usage(self):
        """Optimize memory usage by cleaning up old performance data"""
        try:
            # Limit recent performance history
            max_recent_entries = 50
            if len(self._performance_stats.get("recent_performance", [])) > max_recent_entries:
                self._performance_stats["recent_performance"] = self._performance_stats["recent_performance"][-max_recent_entries:]
                self.logger.debug(f"Trimmed performance history to {max_recent_entries} entries")
            
            # Reset fallback counts if they're very old
            from datetime import timedelta
            cutoff_time = datetime.now() - timedelta(hours=1)
            
            for strategy_name, last_time in list(self._last_fallback_time.items()):
                if last_time and last_time < cutoff_time:
                    self._fallback_counts[strategy_name] = 0
                    self._last_fallback_time[strategy_name] = None
                    self.logger.debug(f"Reset old fallback count for {strategy_name}")
            
            # Force garbage collection
            import gc
            gc.collect()
            
        except Exception as e:
            self.logger.warning(f"Error optimizing memory usage: {e}")
    
    def _update_performance_stats(self, result: TranscriptionResult, start_time: float, is_fallback: bool = False):
        """Update performance statistics"""
        try:
            total_time = time.time() - start_time
            method_name = result.method_used
            
            # Update global stats
            self._performance_stats["total_requests"] += 1
            self._performance_stats["total_processing_time"] += total_time
            
            if result.error_message is None:
                self._performance_stats["successful_requests"] += 1
            else:
                self._performance_stats["failed_requests"] += 1
            
            if is_fallback:
                self._performance_stats["fallback_requests"] += 1
            
            # Update strategy-specific stats
            if method_name not in self._performance_stats["strategy_stats"]:
                self._performance_stats["strategy_stats"][method_name] = {
                    "requests": 0,
                    "successful": 0,
                    "failed": 0,
                    "total_time": 0.0,
                    "avg_time": 0.0
                }
            
            strategy_stats = self._performance_stats["strategy_stats"][method_name]
            strategy_stats["requests"] += 1
            strategy_stats["total_time"] += result.processing_time
            
            if result.error_message is None:
                strategy_stats["successful"] += 1
            else:
                strategy_stats["failed"] += 1
            
            # Calculate average time
            if strategy_stats["requests"] > 0:
                strategy_stats["avg_time"] = strategy_stats["total_time"] / strategy_stats["requests"]
            
            # Update recent performance (rolling window)
            performance_entry = {
                "timestamp": datetime.now(),
                "method": method_name,
                "success": result.error_message is None,
                "processing_time": result.processing_time,
                "fallback": is_fallback
            }
            
            self._performance_stats["recent_performance"].append(performance_entry)
            
            # Keep only last 100 entries
            if len(self._performance_stats["recent_performance"]) > 100:
                self._performance_stats["recent_performance"].pop(0)
                
        except Exception as e:
            self.logger.warning(f"Error updating performance stats: {e}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get current performance statistics"""
        try:
            stats = self._performance_stats.copy()
            
            # Calculate overall averages
            if stats["total_requests"] > 0:
                stats["overall_avg_time"] = stats["total_processing_time"] / stats["total_requests"]
                stats["success_rate"] = stats["successful_requests"] / stats["total_requests"]
                stats["fallback_rate"] = stats["fallback_requests"] / stats["total_requests"]
            else:
                stats["overall_avg_time"] = 0.0
                stats["success_rate"] = 0.0
                stats["fallback_rate"] = 0.0
            
            # Calculate recent performance (last 10 requests)
            recent = stats["recent_performance"][-10:] if stats["recent_performance"] else []
            if recent:
                recent_success = sum(1 for r in recent if r["success"])
                recent_fallback = sum(1 for r in recent if r["fallback"])
                recent_avg_time = sum(r["processing_time"] for r in recent) / len(recent)
                
                stats["recent_success_rate"] = recent_success / len(recent)
                stats["recent_fallback_rate"] = recent_fallback / len(recent)
                stats["recent_avg_time"] = recent_avg_time
            else:
                stats["recent_success_rate"] = 0.0
                stats["recent_fallback_rate"] = 0.0
                stats["recent_avg_time"] = 0.0
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting performance stats: {e}")
            return {}
    
    def get_performance_summary(self) -> str:
        """Get a human-readable performance summary"""
        try:
            stats = self.get_performance_stats()
            
            if stats["total_requests"] == 0:
                return "No transcription requests processed yet"
            
            summary = f"Transcription Performance Summary:\n"
            summary += f"  Total Requests: {stats['total_requests']}\n"
            summary += f"  Success Rate: {stats['success_rate']:.1%}\n"
            summary += f"  Fallback Rate: {stats['fallback_rate']:.1%}\n"
            summary += f"  Average Time: {stats['overall_avg_time']:.2f}s\n"
            
            if stats["strategy_stats"]:
                summary += f"\nBy Method:\n"
                for method, method_stats in stats["strategy_stats"].items():
                    success_rate = method_stats["successful"] / method_stats["requests"] if method_stats["requests"] > 0 else 0
                    summary += f"  {method}: {method_stats['requests']} requests, {success_rate:.1%} success, {method_stats['avg_time']:.2f}s avg\n"
            
            return summary
            
        except Exception as e:
            self.logger.error(f"Error generating performance summary: {e}")
            return "Error generating performance summary"
