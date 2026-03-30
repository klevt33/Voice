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
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from whisper_server_base import check_bearer_auth, load_whisper_model, run_transcription

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
    parser.add_argument("--model", default=None, help="Whisper model name (overrides WHISPER_MODEL from config.py)")
    parser.add_argument("--api-key", default=None, dest="api_key",
                        help="Bearer token required on /transcribe (default: None — auth disabled)")
    return parser.parse_args()


args = _parse_args()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    from config import WHISPER_MODEL, MODEL_SERVICE_PORT
except Exception as _cfg_err:
    logger.error(f"Failed to import config.py: {_cfg_err}")
    sys.exit(1)

MODEL_NAME: str = args.model or WHISPER_MODEL
BIND_PORT: int = args.port if args.port is not None else MODEL_SERVICE_PORT
API_KEY: str | None = args.api_key

# ---------------------------------------------------------------------------
# Model + concurrency
# ---------------------------------------------------------------------------

_whisper_model = load_whisper_model(MODEL_NAME)
_executor = ThreadPoolExecutor(max_workers=1)  # single worker — model is not thread-safe
_transcribe_lock = asyncio.Semaphore(1)        # serialise concurrent requests

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Shared Whisper Model Service")


@app.get("/health")
async def health() -> JSONResponse:
    """Return model readiness. Never requires auth."""
    if _whisper_model is not None:
        return JSONResponse({"status": "ok", "model": MODEL_NAME})
    return JSONResponse({"status": "unavailable", "reason": "Model not loaded"}, status_code=503)


@app.post("/transcribe")
async def transcribe(request: Request) -> JSONResponse:
    """Accept raw WAV bytes and return transcription JSON.

    Concurrent requests are serialised via _transcribe_lock so the
    non-thread-safe WhisperModel is never called from two threads at once.
    The blocking model call runs in a ThreadPoolExecutor so the asyncio
    event loop stays free to accept new connections while transcribing.
    """
    check_bearer_auth(request, API_KEY)

    audio_bytes = await request.body()
    if len(audio_bytes) == 0:
        logger.info("Received empty audio payload — returning empty result.")
        return JSONResponse({"text": "", "processing_time": 0.0})

    logger.info(f"Received audio payload: {len(audio_bytes)} bytes — waiting for lock")
    try:
        async with _transcribe_lock:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(_executor, run_transcription, _whisper_model, audio_bytes)
        return JSONResponse(result)
    except Exception as exc:
        logger.error(f"Transcription failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting ModelService on {args.host}:{BIND_PORT}, model={MODEL_NAME}")
    uvicorn.run(app, host=args.host, port=BIND_PORT)
