"""
transcription_server.py — Standalone FastAPI transcription server.

Runs on a GPU machine and exposes /transcribe and /health endpoints.
When MODEL_SERVICE_ENABLED is True, probes localhost:MODEL_SERVICE_PORT at
startup; if a compatible ModelService is already running (or can be spawned),
all /transcribe requests are forwarded to it instead of loading a second model.

Usage:
    python transcription_server.py
    python transcription_server.py --host 0.0.0.0 --port 8765 --model large-v3 --api-key mysecret
"""

import argparse
import logging
import sys
import time

import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from whisper_server_base import check_bearer_auth, load_whisper_model, run_transcription

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
    parser.add_argument("--model", default=None, help="Whisper model name (overrides WHISPER_MODEL from config.py)")
    parser.add_argument("--api-key", default=None, dest="api_key",
                        help="Bearer token required on /transcribe (default: None — auth disabled)")
    return parser.parse_args()


args = _parse_args()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    from config import WHISPER_MODEL, MODEL_SERVICE_ENABLED, MODEL_SERVICE_API_KEY
except Exception as _cfg_err:
    logger.error(f"Failed to import config.py: {_cfg_err}")
    sys.exit(1)

try:
    from model_service_manager import ModelServiceManager
except Exception as _msm_err:
    logger.error(f"Failed to import ModelServiceManager: {_msm_err}")
    sys.exit(1)

MODEL_NAME: str = args.model or WHISPER_MODEL
API_KEY: str | None = args.api_key

# ---------------------------------------------------------------------------
# Shared ModelService: probe-or-spawn before loading WhisperModel
# ---------------------------------------------------------------------------

_model_service_url: str | None = None

if MODEL_SERVICE_ENABLED:
    _ms_manager = ModelServiceManager()
    _ms_result = _ms_manager.ensure_running()
    if _ms_result.available:
        _model_service_url = _ms_result.url
        logger.info(
            f"ModelService available at {_model_service_url} — "
            f"server will forward /transcribe requests, skipping local model load"
        )
    else:
        _ms_manager.shutdown()
        logger.info("ModelService not available — loading WhisperModel directly")
else:
    logger.debug("ModelService integration disabled (MODEL_SERVICE_ENABLED=False)")

# ---------------------------------------------------------------------------
# Load WhisperModel only when ModelService is not handling requests
# ---------------------------------------------------------------------------

_whisper_model = None
if _model_service_url is None:
    _whisper_model = load_whisper_model(MODEL_NAME)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Transcription Server")


async def _verify_token(request: Request) -> None:
    """FastAPI dependency: enforce Bearer token auth when API_KEY is configured."""
    check_bearer_auth(request, API_KEY)


@app.get("/health")
async def health() -> JSONResponse:
    """Return model readiness. Never requires auth."""
    if _model_service_url is not None:
        return JSONResponse({
            "status": "ok",
            "model": MODEL_NAME,
            "mode": "model_service",
            "model_service_url": _model_service_url,
        })
    if _whisper_model is not None:
        return JSONResponse({"status": "ok", "model": MODEL_NAME})
    return JSONResponse({"status": "unavailable", "reason": "Model not loaded"}, status_code=503)


@app.post("/transcribe", dependencies=[Depends(_verify_token)])
async def transcribe(request: Request) -> JSONResponse:
    """Accept raw WAV bytes and return transcription JSON.

    Forwards to ModelService when available; otherwise transcribes locally.
    """
    audio_bytes = await request.body()

    if len(audio_bytes) == 0:
        logger.info("Received empty audio payload — returning empty result.")
        return JSONResponse({"text": "", "processing_time": 0.0})

    logger.info(f"Received audio payload: {len(audio_bytes)} bytes")

    # Forward to ModelService when available
    if _model_service_url is not None:
        try:
            headers = {"Content-Type": "application/octet-stream"}
            if MODEL_SERVICE_API_KEY:
                headers["Authorization"] = f"Bearer {MODEL_SERVICE_API_KEY}"
            forward_response = requests.post(
                f"{_model_service_url}/transcribe",
                data=audio_bytes,
                headers=headers,
                timeout=60.0,
            )
            if forward_response.status_code == 200:
                return JSONResponse(forward_response.json())
            logger.warning(
                f"ModelService at {_model_service_url} returned "
                f"HTTP {forward_response.status_code}: {forward_response.text}"
            )
            raise HTTPException(status_code=502, detail="ModelService returned an error")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"Failed to forward /transcribe to ModelService at {_model_service_url}: {exc}")
            raise HTTPException(status_code=502, detail=f"ModelService unreachable: {exc}")

    # Local transcription
    start_time = time.time()
    try:
        result = run_transcription(_whisper_model, audio_bytes)
        return JSONResponse(result)
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
