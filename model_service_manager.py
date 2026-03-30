"""
model_service_manager.py — Spawn-or-connect logic for the Shared Whisper Model Service.

Both the App (AudioToChat.py) and the Server (transcription_server.py) call
ModelServiceManager().ensure_running() at startup.  The method probes
localhost:MODEL_SERVICE_PORT; if ModelService is already running it returns a
result pointing to it.  If not, it spawns model_service.py as a child
subprocess and waits for it to become healthy.

Usage:
    manager = ModelServiceManager()
    result = manager.ensure_running()
    if result.available:
        # use result.url with NetworkGPUTranscriptionStrategy
    else:
        # fall back to loading the model in-process

    # On process exit:
    manager.shutdown()
"""

import atexit
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — resolved once at import time
# ---------------------------------------------------------------------------

try:
    from config import (
        MODEL_SERVICE_ENABLED,
        MODEL_SERVICE_URL,
        MODEL_SERVICE_PORT,
        MODEL_SERVICE_STARTUP_TIMEOUT,
        MODEL_SERVICE_API_KEY,
        WHISPER_MODEL,
    )
except ImportError as _cfg_err:
    raise ImportError(f"model_service_manager requires config.py: {_cfg_err}") from _cfg_err


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class HealthProbeResult:
    """Result of a single GET /health probe."""
    reachable: bool                  # True if HTTP 200 received
    model_name: Optional[str]        # value of "model" field, or None
    compatible: bool                 # reachable AND model_name == WHISPER_MODEL


@dataclass
class ModelServiceResult:
    """Result returned by ModelServiceManager.ensure_running()."""
    available: bool                  # ModelService is reachable and compatible
    url: str                         # ModelService base URL
    spawned: bool                    # True if this process spawned ModelService
    pid: Optional[int]               # PID of spawned subprocess, or None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ModelServiceManager:
    """Manages the lifecycle of the shared Whisper ModelService subprocess.

    Call ensure_running() once at startup.  Call shutdown() on exit (or rely
    on the atexit handler registered automatically when a subprocess is spawned).
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._spawned: bool = False
        self._url: str = ""
        self._atexit_registered: bool = False

    # ------------------------------------------------------------------
    # probe
    # ------------------------------------------------------------------

    def probe(self) -> HealthProbeResult:
        """Perform a single GET /health with a 2-second timeout.

        Returns a HealthProbeResult indicating reachability and model
        compatibility against WHISPER_MODEL from config.
        """
        try:
            response = requests.get(f"{MODEL_SERVICE_URL}/health", timeout=2.0)
            if response.status_code != 200:
                return HealthProbeResult(reachable=False, model_name=None, compatible=False)

            data = response.json()
            if data.get("status") != "ok":
                return HealthProbeResult(reachable=False, model_name=None, compatible=False)

            model_name: Optional[str] = data.get("model")
            if model_name is None:
                logger.warning(
                    f"ModelService at {MODEL_SERVICE_URL} did not return a 'model' field — treating as incompatible"
                )
                return HealthProbeResult(reachable=True, model_name=None, compatible=False)

            compatible = (model_name == WHISPER_MODEL)
            if not compatible:
                logger.warning(
                    f"ModelService model '{model_name}' differs from configured '{WHISPER_MODEL}' "
                    f"— falling back to local model load"
                )
            return HealthProbeResult(reachable=True, model_name=model_name, compatible=compatible)

        except Exception:
            return HealthProbeResult(reachable=False, model_name=None, compatible=False)

    # ------------------------------------------------------------------
    # spawn
    # ------------------------------------------------------------------

    def spawn(self) -> Optional[subprocess.Popen]:
        """Launch model_service.py as a child subprocess.

        Returns the Popen object on success, or None if the launch fails.
        """
        # Locate model_service.py relative to this file
        service_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_service.py")
        if not os.path.exists(service_script):
            logger.error(f"model_service.py not found at {service_script}")
            return None

        cmd = [sys.executable, service_script, "--port", str(MODEL_SERVICE_PORT), "--model", WHISPER_MODEL]
        if MODEL_SERVICE_API_KEY:
            cmd += ["--api-key", MODEL_SERVICE_API_KEY]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"ModelService not found at localhost:{MODEL_SERVICE_PORT} — spawning ModelService (pid: {proc.pid})")
            return proc
        except Exception as exc:
            logger.error(f"Failed to spawn ModelService: {exc}")
            return None

    # ------------------------------------------------------------------
    # wait_until_healthy
    # ------------------------------------------------------------------

    def wait_until_healthy(self, proc: subprocess.Popen, timeout: float) -> bool:
        """Poll /health every 0.5s until ModelService is compatible or timeout expires.

        Returns True if ModelService became healthy within the timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Check if the subprocess exited prematurely
            if proc.poll() is not None:
                logger.warning(f"ModelService subprocess (pid: {proc.pid}) exited prematurely with code {proc.returncode}")
                return False
            if self.probe().compatible:
                return True
            time.sleep(0.5)

        logger.warning(
            f"ModelService failed to start within {timeout:.1f}s — falling back to local model load"
        )
        return False

    # ------------------------------------------------------------------
    # ensure_running
    # ------------------------------------------------------------------

    def ensure_running(self) -> ModelServiceResult:
        """Main entry point: probe → connect or spawn → fallback.

        Returns a ModelServiceResult.  If available=True, use result.url
        with ModelServiceTranscriptionStrategy.  If available=False, fall back
        to loading the model in-process.
        """
        self._url = MODEL_SERVICE_URL

        if not MODEL_SERVICE_ENABLED:
            logger.debug("ModelService integration disabled (MODEL_SERVICE_ENABLED=False) — skipping probe/spawn")
            return ModelServiceResult(available=False, url=self._url, spawned=False, pid=None)

        # Step 1: probe — maybe it's already running
        probe_result = self.probe()
        if probe_result.compatible:
            logger.info(
                f"ModelService already running at {self._url} "
                f"(model: {probe_result.model_name}) — connecting, skipping local model load"
            )
            return ModelServiceResult(available=True, url=self._url, spawned=False, pid=None)

        if probe_result.reachable and not probe_result.compatible:
            # Reachable but wrong model — fall back, don't spawn a competing instance
            return ModelServiceResult(available=False, url=self._url, spawned=False, pid=None)

        # Step 2: not running — spawn it
        proc = self.spawn()
        if proc is None:
            logger.warning("ModelService spawn failed — falling back to local model load")
            return ModelServiceResult(available=False, url=self._url, spawned=False, pid=None)

        self._proc = proc
        self._spawned = True

        # Register atexit so ModelService is cleaned up even on unexpected exit
        if not self._atexit_registered:
            atexit.register(self.shutdown)
            self._atexit_registered = True

        # Step 3: wait for it to become healthy
        healthy = self.wait_until_healthy(proc, MODEL_SERVICE_STARTUP_TIMEOUT)
        if not healthy:
            # Terminate the failed subprocess
            self._terminate_proc(proc)
            self._proc = None
            self._spawned = False
            return ModelServiceResult(available=False, url=self._url, spawned=False, pid=None)

        # Final compatibility probe (model name check)
        final_probe = self.probe()
        if not final_probe.compatible:
            self._terminate_proc(proc)
            self._proc = None
            self._spawned = False
            return ModelServiceResult(available=False, url=self._url, spawned=False, pid=None)

        logger.info(
            f"ModelService ready at {self._url} (model: {final_probe.model_name}, pid: {proc.pid})"
        )
        return ModelServiceResult(available=True, url=self._url, spawned=True, pid=proc.pid)

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Terminate the ModelService subprocess if this process spawned it.

        If spawned=False this is a no-op — the subprocess is owned by another
        process and must not be touched.
        """
        if not self._spawned or self._proc is None:
            return

        proc = self._proc
        self._proc = None
        self._spawned = False
        self._terminate_proc(proc)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _terminate_proc(self, proc: subprocess.Popen) -> None:
        """Gracefully terminate a subprocess; force-kill after 5 seconds."""
        if proc.poll() is not None:
            return  # already exited

        logger.info(f"Terminating ModelService subprocess (pid: {proc.pid})")
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"ModelService (pid: {proc.pid}) did not exit in 5s — force killing")
                proc.kill()
                proc.wait()
        except Exception as exc:
            logger.warning(f"Error terminating ModelService (pid: {proc.pid}): {exc}")
