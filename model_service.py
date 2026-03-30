"""
model_service.py — Shared Whisper Model Service.

A lightweight FastAPI subprocess that owns the Whisper model and serves
/health and /transcribe on localhost:MODEL_SERVICE_PORT (default 8766).

Both the App (AudioToChat.py) and the Server (transcription_server.py) use a
spawn-or-connect protocol: whichever starts first spawns this process; the
second simply connects to the already-running instance.

Usage:
    python model_service.py
    python model_service.py --port 8766 --model large-v3 --api-key mysecret
"""

import argparse
import asyncio
import io
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("model_service")

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared Whisper Model Service")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: MODEL_SERVICE_PORT from config)")
    parser.add_argument(
        "--model",
        default=None,
        help="Whisper model name (overrides WHISPER_MODEL from config.py)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        dest="api_key",
        help="Bearer token required on /transcribe (default: None — auth disabled)",
    )
    return parser.parse_args()


args = _parse_args()

# ---------------------------------------------------------------------------
# Load config values
# ---------------------------------------------------------------------------

try:
    from config import (
        WHISPER_MODEL, COMPUTE_TYPE, MODELS_FOLDER, LANGUAGE, BEAM_SIZE,
        MODEL_SERVICE_PORT,
    )
except Exception as _cfg_err:
    logger.error(f"Failed to import config.py: {_cfg_err}")
    sys.exit(1)

try:
    from transcription_strategies import apply_hallucination_filter, process_whisper_segments
except Exception as _filter_err:
    logger.error(f"Failed to import from transcription_strategies: {_filter_err}")
    sys.exit(1)

# CLI args override config
MODEL_NAME: str = args.model if args.model else WHISPER_MODEL
BIND_PORT: int = args.port if args.port is not None else MODEL_SERVICE_PORT
API_KEY: str | None = args.api_key

# ---------------------------------------------------------------------------
# Load faster-whisper model at startup
# ---------------------------------------------------------------------------

_whisper_model = None
_executor = ThreadPoolExecutor(max_workers=1)  # single worker — model is not thread-safe

try:
    import os
    import torch
    from faster_whisper import WhisperModel

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _compute_type = COMPUTE_TYPE if _device == "cuda" else "int8"

    if not os.path.exists(MODELS_FOLDER):
        os.makedirs(MODELS_FOLDER)

    logger.info(f"Loading faster-whisper model '{MODEL_NAME}' on {_device} ({_compute_type}) …")
    _whisper_model = WhisperModel(
        MODEL_NAME,
        device=_device,
        compute_type=_compute_type,
        download_root=MODELS_FOLDER,
    )
    logger.info(f"Model '{MODEL_NAME}' loaded successfully.")

except Exception as _model_err:
    logger.error(f"Failed to load faster-whisper model: {_model_err}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Shared Whisper Model Service")

# Semaphore ensures only one transcription runs at a time.
# Concurrent requests queue at the uvicorn layer and are processed serially.
_transcribe_lock = asyncio.Semaphore(1)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_auth(request: Request) -> None:
    """Raise HTTP 401 if API_KEY is set and the request does not carry it."""
    if API_KEY is None:
        return
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if auth_header[len("Bearer "):] != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Blocking transcription helper (runs in thread pool)
# ---------------------------------------------------------------------------

def _do_transcribe(audio_bytes: bytes) -> dict:
    """Run faster-whisper synchronously; called via run_in_executor."""
    start_time = time.time()
    with io.BytesIO(audio_bytes) as audio_io:
        segments, _info = _whisper_model.transcribe(
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    """Return model readiness. Never requires auth."""
    if _whisper_model is not None:
        return JSONResponse({"status": "ok", "model": MODEL_NAME})
    return JSONResponse(
        {"status": "unavailable", "reason": "Model not loaded"},
        status_code=503,
    )


@app.post("/transcribe")
async def transcribe(request: Request) -> JSONResponse:
    """Accept raw WAV bytes and return transcription JSON.

    Concurrent requests are serialized via _transcribe_lock so the
    non-thread-safe WhisperModel is never called from two threads at once.
    The blocking model call runs in a ThreadPoolExecutor so the asyncio
    event loop stays free to accept new connections while transcribing.
    """
    _check_auth(request)

    audio_bytes = await request.body()

    if len(audio_bytes) == 0:
        logger.info("Received empty audio payload — returning empty result.")
        return JSONResponse({"text": "", "processing_time": 0.0})

    logger.info(f"Received audio payload: {len(audio_bytes)} bytes — waiting for lock")

    try:
        async with _transcribe_lock:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(_executor, _do_transcribe, audio_bytes)
        return JSONResponse(result)
    except Exception as exc:
        logger.error(f"Transcription failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting ModelService on 127.0.0.1:{BIND_PORT}, model={MODEL_NAME}")
    uvicorn.run(app, host=args.host, port=BIND_PORT)
