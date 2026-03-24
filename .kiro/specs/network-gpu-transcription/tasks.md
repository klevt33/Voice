# Implementation Plan: Network GPU Transcription

## Overview

Add a third transcription strategy that sends audio over HTTP to a faster-whisper server running on a GPU machine on the local network. The work splits into: (1) config additions, (2) the FastAPI server script, (3) the client strategy class, (4) wiring into `transcription.py`, and (5) replacing the binary checkbox in `ui_view.py` with a multi-option dropdown.

## Tasks

- [x] 1. Add Network GPU configuration constants to `config.py`
  - Add `NETWORK_GPU_SERVER_URL = "http://localhost:8765"`, `NETWORK_GPU_TIMEOUT = 30.0`, `NETWORK_GPU_ENABLED = False`, `NETWORK_GPU_API_KEY = None` constants
  - Add `"network_gpu"` to the `valid_methods` list inside `validate_transcription_config()`
  - Add `"network_gpu_enabled"` and `"network_gpu_server_url"` keys to the validation results dict
  - Add error when `NETWORK_GPU_ENABLED` is `True` and `NETWORK_GPU_SERVER_URL` is empty
  - Add warning when `DEFAULT_TRANSCRIPTION_METHOD == "network_gpu"` and `NETWORK_GPU_ENABLED` is `False`
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

  - [ ]* 1.1 Write unit tests for updated `validate_transcription_config()`
    - Test `NETWORK_GPU_ENABLED=True` + empty URL → error present
    - Test `DEFAULT_TRANSCRIPTION_METHOD="network_gpu"` + `NETWORK_GPU_ENABLED=False` → warning present
    - Test `"network_gpu"` accepted as valid method value
    - _Requirements: 6.6_

- [x] 2. Implement `NetworkGPUTranscriptionStrategy` in `transcription_strategies.py`
  - Add class implementing `TranscriptionStrategy` ABC with `get_name()` returning `"Network GPU"`
  - Implement `is_available()`: GET `{NETWORK_GPU_SERVER_URL}/health` with 3 s timeout; return `True` only on HTTP 200 + `status == "ok"`; cache result for 10 s using `time.monotonic()`
  - Implement `transcribe()`: call `audio_segment.get_wav_bytes()`, POST to `{NETWORK_GPU_SERVER_URL}/transcribe` with `Content-Type: application/octet-stream` and optional `Authorization: Bearer` header; parse JSON on 200; return `TranscriptionResult(method_used="network_gpu", ...)`; catch `ConnectionError`, `Timeout`, and HTTP errors — never raise
  - Import `requests` at the top of the file (add to `requirements.in` if not present)
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 11.3_

  - [ ]* 2.1 Write unit tests for `NetworkGPUTranscriptionStrategy.transcribe()`
    - Mock `requests.post` returning 200, 401, 500, `ConnectionError`, `Timeout`
    - Assert `method_used == "network_gpu"` in all cases
    - Assert no exception is raised in any case
    - Assert `text == ""` and `error_message` is set for all failure cases
    - _Requirements: 4.3, 4.5, 4.6_

  - [ ]* 2.2 Write property test for error containment (Property 5)
    - **Property 5: Error containment**
    - **Validates: Requirements 4.5, 10.3**
    - Use `hypothesis` to generate varied `ConnectionError`/`Timeout` side effects; assert `result.text == ""` and `result.error_message is not None` for all

  - [ ]* 2.3 Write unit tests for `NetworkGPUTranscriptionStrategy.is_available()` caching
    - Two calls within 10 s should issue exactly one HTTP GET
    - A call after cache TTL expires should issue a second HTTP GET
    - _Requirements: 5.5_

  - [ ]* 2.4 Write property test for availability caching (Property 4)
    - **Property 4: Availability caching**
    - **Validates: Requirements 5.5**
    - Use `hypothesis` with `n` in [2, 20]; assert `mock_requests.get.call_count == 1` for all `n` calls within cache window

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create `transcription_server.py` at the project root
  - Parse CLI args: `--host` (default `0.0.0.0`), `--port` (default `8765`), `--model` (default `WHISPER_MODEL`), `--api-key` (default `None`)
  - Load faster-whisper model at startup using `WHISPER_MODEL`, `COMPUTE_TYPE`, `MODELS_FOLDER`, `LANGUAGE`, `BEAM_SIZE` from `config.py`; on failure log error and `sys.exit(1)`
  - Implement `GET /health`: return `{"status": "ok", "model": model_name}` (200) when model is loaded, `{"status": "unavailable", "reason": "..."}` (503) otherwise
  - Implement `POST /transcribe`: accept `application/octet-stream` body; run faster-whisper with same params as `LocalGPUTranscriptionStrategy`; apply identical hallucination filter; return `{"text": "...", "processing_time": ...}` (200) or `{"detail": "..."}` (500)
  - Implement Bearer token auth dependency: if `--api-key` set, check `Authorization` header on all routes except `/health`; return 401 on mismatch
  - Handle empty/zero-length payload gracefully — return `{"text": "", "processing_time": 0.0}` (200)
  - Log each request: audio size, processing time, result length
  - Log bound address and model name on successful startup
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 11.1, 11.2, 11.5_

  - [ ]* 4.1 Write unit tests for server endpoints using FastAPI `TestClient`
    - `POST /transcribe` with valid WAV bytes → 200 + JSON with `text` key
    - `GET /health` before model loaded → 503
    - `GET /health` after model loaded → 200 with `status == "ok"`
    - `POST /transcribe` without token when `--api-key` set → 401
    - `POST /transcribe` with correct token → 200
    - Empty body → 200 with `text == ""`
    - _Requirements: 1.1, 1.3, 1.4, 3.2, 3.3, 11.2_

  - [ ]* 4.2 Write property test for auth enforcement (Property 6)
    - **Property 6: Auth enforcement**
    - **Validates: Requirements 11.1, 11.2, 11.3**
    - Use `hypothesis` to generate arbitrary tokens; assume token != correct key; assert response is 401; assert correct token returns 200

  - [ ]* 4.3 Write property test for empty audio handling (Property 7)
    - **Property 7: Empty audio handling**
    - **Validates: Requirements 1.3**
    - Use `hypothesis` to generate zero-length or silence-only WAV payloads; assert HTTP 200 and `text == ""`

  - [x] 4.4 Write property test for hallucination filter consistency (Property 2)
    - **Property 2: Hallucination filter consistency**
    - **Validates: Requirements 1.5**
    - Extract the filter logic from both `LocalGPUTranscriptionStrategy` and `transcription_server.py` into a shared helper or test both independently; use `hypothesis` text generation; assert both produce identical output for all inputs

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Wire `NetworkGPUTranscriptionStrategy` into `transcription.py`
  - In `initialize_transcription_manager()`, after the Groq block, add: if `NETWORK_GPU_ENABLED`, import and register `NetworkGPUTranscriptionStrategy` with `priority=3`, `retry_count=0`
  - Add `"network_gpu"` and `"network"` keys to `strategy_mapping` in `switch_transcription_method()`
  - Add `"network_gpu"` primary strategy selection branch (parallel to `"local"` / `"api"` branches)
  - Add network error branch to `_handle_transcription_error()`: match `"connection failed"` or `("network" and "gpu")` → `notify_exception(..., "warning", "Network GPU unreachable - Check server")`
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 10.1, 10.2, 10.5_

  - [ ]* 6.1 Write unit tests for `initialize_transcription_manager()` with network GPU config
    - `NETWORK_GPU_ENABLED=False` → `"Network GPU"` absent from `get_available_strategies()`
    - `NETWORK_GPU_ENABLED=True` → `"Network GPU"` present
    - `DEFAULT_TRANSCRIPTION_METHOD="network_gpu"` → network strategy set as primary
    - _Requirements: 6.5, 7.1, 7.2_

  - [ ]* 6.2 Write property test for strategy registration gating (Property 8)
    - **Property 8: Strategy registration gating**
    - **Validates: Requirements 6.5**
    - Use `hypothesis` with `enabled=st.just(False)`; monkeypatch `NETWORK_GPU_ENABLED`; assert `"Network GPU"` not in `manager.get_available_strategies()`

  - [ ]* 6.3 Write unit test for `switch_transcription_method("network_gpu")`
    - Assert it maps to `"Network GPU"` strategy name
    - _Requirements: 7.3_

- [x] 7. Replace binary checkbox with `ttk.OptionMenu` dropdown in `ui_view.py`
  - Remove `_create_transcription_method_toggle_title_level()`, the old `update_transcription_method_control(gpu_available, api_available, current_method)` signature, and `self.transcription_method_checkbox`
  - Add `_create_transcription_method_selector()`: create `ttk.OptionMenu` bound to `tk.StringVar`; place at `relx=1.0, rely=0.0, anchor="ne", x=-10, y=-25`; initially hidden
  - Add new `update_transcription_method_control(available_methods: dict, current_method: str)`: rebuild menu options from `available_methods`; disable when only one option; hide when none
  - Update `get_transcription_method_preference()` to return `str` (selected display name) instead of `bool`
  - Add `"transcription_network_gpu": ("#006400", "Transcription: Network GPU")` to `status_colors`
  - Extend `update_transcription_status()` to detect `"network"` or `"network_gpu"` in `method_lower` → use `"transcription_network_gpu"` key
  - Replace call to `_create_transcription_method_toggle_title_level()` in `create_widgets()` with `_create_transcription_method_selector()`
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3_

  - [ ]* 7.1 Write unit tests for `update_transcription_method_control()`
    - One available method → dropdown disabled
    - Three available methods → dropdown enabled with three options
    - No available methods → dropdown hidden
    - _Requirements: 8.1, 8.3, 8.5_

- [x] 8. Add `fastapi`, `uvicorn[standard]`, and `requests` to `requirements.in`
  - _Requirements: (dependency for server and client)_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- `transcription_server.py` is a standalone script — it is never imported by the client
- Property tests use `hypothesis`; run with `pytest tests/` or `pytest --hypothesis-seed=0`
- The existing `TranscriptionManager` fallback logic requires no changes; it activates automatically when `transcribe()` returns a result with a non-None `error_message`
