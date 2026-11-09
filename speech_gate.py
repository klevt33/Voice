# speech_gate.py
"""Client-side speech gate using faster-whisper's bundled Silero VAD.

Recorded audio is triggered by an amplitude threshold only, so breathing,
keyboard noise and background sounds become Whisper input — the main source of
hallucinated topics on the turbo model.  This gate runs Silero VAD on the
recorded clip *before* any transcription backend is called and lets the caller
skip clips that contain no real speech.  Because it runs client-side it also
protects the Groq API path and saves GPU/network work.

Auto-disabled (returns "proceed") when faster-whisper is not installed, e.g.
API-only installs.
"""
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_availability: Optional[bool] = None


def speech_gate_available() -> bool:
    """True when faster-whisper and its bundled Silero VAD can be imported."""
    global _availability
    if _availability is not None:
        return _availability
    try:
        import faster_whisper.audio  # noqa: F401
        import faster_whisper.vad  # noqa: F401
        _availability = True
    except Exception as exc:
        logger.warning(f"Speech gate disabled — faster-whisper VAD unavailable: {exc}")
        _availability = False
    return _availability


def contains_speech(
    wav_bytes: bytes,
    min_speech_s: float,
    threshold: float,
) -> Optional[bool]:
    """Check whether a WAV clip contains at least `min_speech_s` of speech.

    Returns True/False for a definitive answer, or None when the check itself
    could not run (decode/VAD failure) — the caller should then proceed with
    transcription rather than drop audio.
    """
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        audio = decode_audio(io.BytesIO(wav_bytes), sampling_rate=16000)
        speech_chunks = get_speech_timestamps(
            audio,
            vad_options=VadOptions(
                threshold=threshold,
                min_speech_duration_ms=100,
                speech_pad_ms=200,
            ),
            sampling_rate=16000,
        )
    except Exception as exc:
        logger.warning(f"Speech gate check failed ({exc}) — proceeding without gate")
        return None

    total_speech_s = sum(c["end"] - c["start"] for c in speech_chunks) / 16000.0
    logger.debug(f"Speech gate: {total_speech_s:.2f}s speech detected "
                 f"(minimum {min_speech_s}s)")
    return total_speech_s >= min_speech_s
