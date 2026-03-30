# Implementation Plan: Shared Whisper Model Service

## Overview

Introduce `model_service.py` and `model_service_manager.py` to enable a spawn-or-connect protocol that lets the App and the Server share a single Whisper model process, eliminating duplicate VRAM usage. Both processes probe `localhost:8766` at startup; whichever starts first spawns ModelService, the second simply connects.

## Tasks

- [x] 1. Add ModelService configuration to `config.py`
  - Add `MODEL_SERVICE_ENABLED = True` (bool)
  - Add `MODEL_SERVICE_PORT = 8766` (int)
  - Add `MODEL_SERVICE_STARTUP_TIMEOUT = 30.0` (float, seconds)
  - Add `MODEL_SERVICE_API_KEY = None` (optional str)
  - Derive `MODEL_SERVICE_URL = f"http://localhost:{MODEL_SERVICE_PORT}"`
  - _Requirements: 8.1, 8.2, 8.3, 8.5_

- [x] 2. Create `model_service.py` — standalone FastAPI transcription process
  - [x] 2.1 Implement CLI argument parsing (`--port`, `--model`, `--api-key`) and model loading
    - Mirror the structure of `transcription_server.py`
    - Exit with non-zero code and log error if `WhisperModel` fails to load
    - Reuse `process_whisper_segments` and `apply_hallucination_filter` from `transcription_strategies.py`
    - _Requirements: 1.3, 1.4, 1.5_

  - [x] 2.2 Implement `/health` and `/transcribe` endpoints with concurrency serialization
    - `/health` returns `{"status": "ok", "model": "<name>"}` with HTTP 200 when ready
    - `/transcribe` accepts raw WAV bytes via POST, returns `{"text": "...", "processing_time": <s>}`
    - Use `asyncio.Semaphore(1)` + `run_in_executor` to serialize blocking model calls
    - Empty payload returns `{"text": "", "processing_time": 0.0}` with HTTP 200
    - _Requirements: 1.1, 1.2_

  - [x] 2.3 Implement optional Bearer token auth on `/transcribe`
    - When `--api-key` is set, enforce `Authorization: Bearer <key>` on `/transcribe`; return HTTP 401 otherwise
    - `/health` never requires auth
    - _Requirements: 1.6_

  - [ ]* 2.4 Write property test for health probe round-trip (Property 1)
    - **Property 1: Health probe round-trip**
    - Generate random model name strings; assert `/health` always returns `{"status": "ok", "model": <name>}` with HTTP 200
    - `# Feature: shared-whisper-model, Property 1: Health probe round-trip`
    - **Validates: Requirements 1.1, 3.1**

  - [ ]* 2.5 Write property test for transcription endpoint accepts arbitrary WAV bytes (Property 2)
    - **Property 2: Transcription endpoint accepts arbitrary WAV bytes**
    - Generate random valid WAV byte sequences; assert HTTP 200, `"text"` is str, `"processing_time"` ≥ 0
    - `# Feature: shared-whisper-model, Property 2: Transcription endpoint accepts arbitrary WAV bytes`
    - **Validates: Requirements 1.2**

  - [ ]* 2.6 Write property test for auth enforcement (Property 3)
    - **Property 3: Auth enforcement on /transcribe**
    - Generate random API key strings and random bearer tokens; assert only exact match returns 200, all others return 401
    - `# Feature: shared-whisper-model, Property 3: Auth enforcement on /transcribe`
    - **Validates: Requirements 1.6**

  - [ ]* 2.7 Write property test for concurrent request serialization (Property 10)
    - **Property 10: Concurrent request serialization**
    - Generate N concurrent requests (N from 1–5) to a mocked `/transcribe`; assert all return HTTP 200 with valid JSON, none return 429 or 503
    - `# Feature: shared-whisper-model, Property 10: Concurrent request serialization`
    - **Validates: Concurrency requirement**

- [x] 3. Create `model_service_manager.py` — spawn-or-connect logic
  - [x] 3.1 Implement `HealthProbeResult` and `ModelServiceResult` dataclasses
    - `HealthProbeResult`: `reachable: bool`, `model_name: str | None`, `compatible: bool`
    - `ModelServiceResult`: `available: bool`, `url: str`, `spawned: bool`, `pid: int | None`
    - _Requirements: 3.1, 3.2_

  - [x] 3.2 Implement `ModelServiceManager.probe()` — single health probe with 2-second timeout
    - GET `{MODEL_SERVICE_URL}/health` with 2s timeout
    - Compare `model` field against `WHISPER_MODEL` from config to set `compatible`
    - Return `HealthProbeResult(reachable=False, ...)` on any exception
    - Log DEBUG when skipped, INFO when connected, WARNING on mismatch
    - _Requirements: 2.6, 3.1, 3.2, 3.3, 3.4, 9.1, 9.2, 9.5_

  - [x] 3.3 Implement `ModelServiceManager.spawn()` and `wait_until_healthy()`
    - `spawn()`: launch `python model_service.py --port <PORT> [--model <MODEL>] [--api-key <KEY>]` as subprocess
    - `wait_until_healthy()`: poll `probe()` every 0.5s up to `MODEL_SERVICE_STARTUP_TIMEOUT`; return bool
    - Log INFO with pid on successful spawn, WARNING on timeout
    - _Requirements: 2.4, 2.5, 6.1, 9.3, 9.4_

  - [x] 3.4 Implement `ModelServiceManager.ensure_running()` — main entry point
    - Probe first; if compatible return `ModelServiceResult(available=True, spawned=False)`
    - If probe fails: spawn → wait_until_healthy → probe again for compatibility check
    - If spawn fails or times out: return `ModelServiceResult(available=False, ...)`
    - If `MODEL_SERVICE_ENABLED=False`: return `available=False` immediately with DEBUG log
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 6.5, 8.4_

  - [x] 3.5 Implement `ModelServiceManager.shutdown()` — lifecycle cleanup
    - If `spawned=True`: terminate subprocess, wait up to 5s, then force-kill
    - If `spawned=False`: no-op
    - Log INFO when terminating with pid
    - Register `atexit` handler inside `ensure_running()` when a subprocess is spawned
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.6_

  - [ ]* 3.6 Write property test for spawn-or-connect idempotence (Property 4)
    - **Property 4: Spawn-or-connect idempotence**
    - Simulate two concurrent `ensure_running()` calls against a pre-running mock service; assert both return `spawned=False` and identical URLs
    - `# Feature: shared-whisper-model, Property 4: Spawn-or-connect idempotence`
    - **Validates: Requirements 2.3**

  - [ ]* 3.7 Write property test for model compatibility check (Property 5)
    - **Property 5: Model compatibility check**
    - Generate pairs of (service_model_name, configured_model_name); assert `available=False` when they differ, `available=True` when they match
    - `# Feature: shared-whisper-model, Property 5: Model compatibility check`
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 3.8 Write property test for fallback on spawn failure (Property 6)
    - **Property 6: Fallback on spawn failure**
    - Generate random timeout values (0.1–5.0s); simulate a ModelService that never becomes healthy; assert `ensure_running()` always returns `available=False` without raising
    - `# Feature: shared-whisper-model, Property 6: Fallback on spawn failure`
    - **Validates: Requirements 6.1, 6.2**

  - [ ]* 3.9 Write property test for feature flag disabling all logic (Property 7)
    - **Property 7: Feature flag disables all probe/spawn logic**
    - Generate arbitrary config states with `MODEL_SERVICE_ENABLED=False`; assert zero HTTP calls to `MODEL_SERVICE_URL` and no subprocess spawned
    - `# Feature: shared-whisper-model, Property 7: Feature flag disables all probe/spawn logic`
    - **Validates: Requirements 6.5, 8.4**

  - [ ]* 3.10 Write property test for lifecycle — spawning parent terminates ModelService (Property 8)
    - **Property 8: Lifecycle — spawning parent terminates ModelService on exit**
    - Generate random subprocess mock objects; call `shutdown()`; assert subprocess is terminated within 5 seconds
    - `# Feature: shared-whisper-model, Property 8: Lifecycle — spawning parent terminates ModelService on exit`
    - **Validates: Requirements 7.1, 7.5**

  - [ ]* 3.11 Write property test for non-spawning process does not affect lifecycle (Property 9)
    - **Property 9: Non-spawning process does not affect ModelService lifecycle**
    - Generate `ModelServiceResult` instances with `spawned=False`; call `shutdown()`; assert no termination signal sent
    - `# Feature: shared-whisper-model, Property 9: Non-spawning process does not affect ModelService lifecycle`
    - **Validates: Requirements 7.3**

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Integrate ModelService into `transcription.py`
  - [x] 5.1 Update `initialize_transcription_manager()` to call `ModelServiceManager.ensure_running()`
    - Import `MODEL_SERVICE_ENABLED`, `MODEL_SERVICE_URL` from `config`; import `ModelServiceManager` from `model_service_manager`
    - When `MODEL_SERVICE_ENABLED` and `DEFAULT_TRANSCRIPTION_METHOD in ("local", "auto")`: call `ensure_running()`
    - If `result.available`: register `NetworkGPUStrategy` pointing to `result.url` as primary (priority 1); skip `LocalGPUStrategy` initialization; log INFO per Req 4.3
    - If not `result.available`: proceed with existing `LocalGPUStrategy` path unchanged
    - Store `ModelServiceManager` instance on module for cleanup
    - _Requirements: 2.1, 2.7, 4.1, 4.2, 4.3, 4.4_

  - [x] 5.2 Update `cleanup_transcription_system()` to call `manager.shutdown()`
    - Call `_model_service_manager.shutdown()` if the module-level instance is set
    - _Requirements: 7.1, 7.4_

  - [ ]* 5.3 Write unit tests for `initialize_transcription_manager()` ModelService integration
    - Test: registers `NetworkGPUStrategy` (not `LocalGPUStrategy`) when `ensure_running()` returns `available=True`
    - Test: falls back to `LocalGPUStrategy` when `ensure_running()` returns `available=False`
    - Test: skips all ModelService logic when `DEFAULT_TRANSCRIPTION_METHOD` is `"api"` or `"network_gpu"`
    - _Requirements: 2.7, 4.1, 4.2_

- [x] 6. Integrate ModelService into `transcription_server.py`
  - [x] 6.1 Add ModelService probe-and-forward logic at server startup
    - Import `MODEL_SERVICE_ENABLED` from `config`; import `ModelServiceManager` from `model_service_manager`
    - Before loading `WhisperModel`: if `MODEL_SERVICE_ENABLED`, call `ModelServiceManager().ensure_running()`
    - If `result.available`: store `result.url`; skip `WhisperModel` loading
    - If not `result.available`: load `WhisperModel` directly as before (no behavior change)
    - _Requirements: 2.2, 5.1, 5.3_

  - [x] 6.2 Update `/health` endpoint to reflect ModelService mode
    - When using ModelService: return `{"status": "ok", "model": MODEL_NAME, "mode": "model_service", "model_service_url": "<url>"}`
    - When using local model: return existing response unchanged
    - _Requirements: 5.2_

  - [x] 6.3 Update `/transcribe` endpoint to forward requests to ModelService
    - When using ModelService: forward raw WAV bytes via `httpx` (or `requests`) POST to `{model_service_url}/transcribe`; propagate auth header if `MODEL_SERVICE_API_KEY` is set
    - On forwarding failure: return HTTP 502 and log WARNING with target URL and error
    - When using local model: existing transcription logic unchanged
    - _Requirements: 5.1, 5.4, 9.7_

  - [ ]* 6.4 Write unit tests for server ModelService integration
    - Test: `/health` includes `mode="model_service"` and `model_service_url` when using ModelService
    - Test: server returns HTTP 502 when forwarded request to ModelService fails
    - Test: `MODEL_SERVICE_ENABLED=False` causes zero HTTP calls to ModelService URL
    - _Requirements: 5.2, 5.4, 6.5_

- [x] 7. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests use Hypothesis with a minimum of 100 examples per property
- Each property test file should include the comment tag `# Feature: shared-whisper-model, Property <N>: <text>`
- `model_service.py` intentionally mirrors `transcription_server.py` structure for consistency
- The `asyncio.Semaphore(1)` + `run_in_executor` pattern in `model_service.py` handles the 2-client concurrency without external infrastructure
