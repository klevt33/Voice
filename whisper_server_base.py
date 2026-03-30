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


def run_transcription(model, audio_bytes: bytes) -> dict:
    """Run faster-whisper on raw WAV bytes synchronously.

    Intended to be called from a ThreadPoolExecutor so the asyncio event loop
    is not blocked.  Returns a dict with "text" and "processing_time" keys.
    """
    from config import LANGUAGE, BEAM_SIZE
    from transcription_strategies import process_whisper_segments

    start_time = time.time()
    with io.BytesIO(audio_bytes) as audio_io:
        segments, _info = model.transcribe(
            audio_io,
            language=LANGUAGE,
            beam_size=BEAM_SIZE,
            word_timestamps=False,
        )
        result_text = process_whisper_segments(segments)

    processing_time = time.time() - start_time
    logger.info(
        f"Transcription complete: {processing_time:.3f}s, "
        f"result length={len(result_text)} chars"
    )
    return {"text": result_text, "processing_time": processing_time}
