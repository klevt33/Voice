"""
whisper_server_base.py — Shared utilities for Whisper HTTP server processes.

Used by both model_service.py and transcription_server.py to avoid duplicating
model loading, auth checking, and transcription logic.
"""

import io
import logging
import os
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)


def load_whisper_model(model_name: str):
    """Load a faster-whisper WhisperModel onto the best available device.

    Exits the process with code 1 on failure — both server scripts treat a
    missing model as a fatal startup error.

    Returns the loaded WhisperModel instance.
    """
    try:
        import torch
        from faster_whisper import WhisperModel
        from config import COMPUTE_TYPE, MODELS_FOLDER
    except ImportError as exc:
        logger.error(f"Missing dependency for model loading: {exc}")
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = COMPUTE_TYPE if device == "cuda" else "int8"

    if not os.path.exists(MODELS_FOLDER):
        os.makedirs(MODELS_FOLDER)

    logger.info(f"Loading faster-whisper model '{model_name}' on {device} ({compute_type}) …")
    try:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=MODELS_FOLDER,
        )
        logger.info(f"Model '{model_name}' loaded successfully.")
        return model
    except Exception as exc:
        logger.error(f"Failed to load faster-whisper model '{model_name}': {exc}")
        sys.exit(1)


def check_bearer_auth(request, api_key: Optional[str]) -> None:
    """Raise HTTP 401 if api_key is set and the request does not carry it.

    Works with both FastAPI Request objects (sync and async contexts).
    Raises fastapi.HTTPException on auth failure.
    """
    if api_key is None:
        return
    from fastapi import HTTPException
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header[len("Bearer "):] != api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


def run_transcription(model, audio_bytes: bytes, word_timestamps=None) -> dict:
    """Run faster-whisper on raw WAV bytes synchronously.

    Intended to be called from a ThreadPoolExecutor so the asyncio event loop
    is not blocked.  Returns a dict with "text", "processing_time" and
    "segments" keys.  "segments" carries per-utterance timing and, when word
    timestamps are enabled, per-word timing used by client-side speaker
    splitting.

    word_timestamps=None resolves to config (WHISPER_WORD_TIMESTAMPS or
    SPEAKER_SPLIT_ENABLED); callers may pass True/False to override — the
    /transcribe endpoint maps the ?word_timestamps= query param onto it so a
    client that splits speakers can request timings regardless of server
    config.
    """
    from config import (
        LANGUAGE, BEAM_SIZE, WHISPER_HOTWORDS, WHISPER_INITIAL_PROMPT,
        WHISPER_VAD_ENABLED, WHISPER_VAD_PARAMETERS,
        WHISPER_CONDITION_ON_PREV_TEXT, WHISPER_REPETITION_PENALTY,
        WHISPER_NO_REPEAT_NGRAM_SIZE, WHISPER_WORD_TIMESTAMPS,
        SPEAKER_SPLIT_ENABLED,
    )
    from transcription_strategies import process_whisper_segments

    # Speaker splitting needs word timings even if not explicitly requested.
    if word_timestamps is None:
        word_timestamps = WHISPER_WORD_TIMESTAMPS or SPEAKER_SPLIT_ENABLED

    hotwords_str = " ".join(WHISPER_HOTWORDS) if WHISPER_HOTWORDS else None
    initial_prompt = WHISPER_INITIAL_PROMPT if WHISPER_INITIAL_PROMPT else None
    logger.debug(
        f"Transcribing with hotwords={'%d words' % len(WHISPER_HOTWORDS) if WHISPER_HOTWORDS else 'disabled'}, "
        f"initial_prompt={'set' if initial_prompt else 'disabled'}, "
        f"vad={'on' if WHISPER_VAD_ENABLED else 'off'}"
    )

    start_time = time.time()
    with io.BytesIO(audio_bytes) as audio_io:
        segments, _info = model.transcribe(
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
    logger.info(
        f"Transcription complete: {processing_time:.3f}s, "
        f"result length={len(result_text)} chars"
    )
    return {
        "text": result_text,
        "processing_time": processing_time,
        "segments": response_segments,
    }