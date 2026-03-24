"""
transcription_server.py — Standalone FastAPI transcription server.

Runs on a GPU machine and exposes /transcribe and /health endpoints.
Usage:
    python transcription_server.py
    python transcription_server.py --host 0.0.0.0 --port 8765 --model large-v3 --api-key mysecret
"""

import argparse
import io
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("transcription_server")

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="faster-whisper transcription server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
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
    from config import WHISPER_MODEL, COMPUTE_TYPE, MODELS_FOLDER, LANGUAGE, BEAM_SIZE
except Exception as _cfg_err:
    logger.error(f"Failed to import config.py: {_cfg_err}")
    sys.exit(1)

try:
    from transcription_strategies import apply_hallucination_filter, process_whisper_segments
except Exception as _filter_err:
    logger.error(f"Failed to import from transcription_strategies: {_filter_err}")
    sys.exit(1)

# CLI --model overrides config
MODEL_NAME: str = args.model if args.model else WHISPER_MODEL
API_KEY: str | None = args.api_key

# ---------------------------------------------------------------------------
# Load faster-whisper model at startup
# ---------------------------------------------------------------------------

_whisper_model = None

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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Transcription Server")

# ---------------------------------------------------------------------------
# Auth dependency (applied to /transcribe only)
# ---------------------------------------------------------------------------

async def _verify_token(request: Request) -> None:
    """FastAPI dependency: enforce Bearer token auth when API_KEY is configured."""
    if API_KEY is None:
        return  # auth disabled
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header[len("Bearer "):]
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


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


@app.post("/transcribe", dependencies=[Depends(_verify_token)])
async def transcribe(request: Request) -> JSONResponse:
    """Accept raw WAV bytes and return transcription JSON."""
    audio_bytes = await request.body()
    audio_size = len(audio_bytes)

    # Handle empty / zero-length payload
    if audio_size == 0:
        logger.info("Received empty audio payload — returning empty result.")
        return JSONResponse({"text": "", "processing_time": 0.0})

    logger.info(f"Received audio payload: {audio_size} bytes")

    start_time = time.time()
    try:
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
        return JSONResponse({"text": result_text, "processing_time": processing_time})

    except Exception as exc:
        processing_time = time.time() - start_time
        logger.error(f"Transcription failed after {processing_time:.3f}s: {exc}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting transcription server on {args.host}:{args.port}, model={MODEL_NAME}")
    uvicorn.run(app, host=args.host, port=args.port)
