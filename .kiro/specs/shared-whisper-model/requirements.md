# Requirements Document

## Introduction

When AudioToChat runs in local GPU mode on the same machine as `transcription_server.py`, both processes independently load the Whisper model into GPU memory. This wastes VRAM — often 3–6 GB for large-v3 — and can cause out-of-memory errors or degraded performance.

This feature introduces a dedicated **ModelService**: a lightweight, standalone FastAPI process that owns the Whisper model and exposes the same `/health` and `/transcribe` HTTP interface as the existing `transcription_server.py`. Both the App and the Server always talk to ModelService via `NetworkGPUTranscriptionStrategy` instead of loading the model in-process.

**Spawn-or-connect protocol:** Whichever process starts first (App or Server) checks whether ModelService is already listening on localhost. If not, it spawns ModelService as a child subprocess. The second process to start finds ModelService already running and simply connects to it — no model loading, no proxy mode, no bidirectional probing between App and Server.

If ModelService cannot be started or becomes unreachable, both processes fall back to their existing behavior: the App loads `LocalGPUStrategy` and the Server loads `WhisperModel` directly.

## Glossary

- **App**: The AudioToChat application process (`AudioToChat.py` and supporting modules).
- **Server**: The standalone transcription server process (`transcription_server.py`), exposing `/health` and `/transcribe` HTTP endpoints.
- **ModelService**: The new lightweight FastAPI subprocess (`model_service.py`) that loads the Whisper model and exposes `/health` and `/transcribe` endpoints on localhost.
- **ModelService_Port**: The localhost TCP port on which ModelService listens (default: `8766`, configurable via `MODEL_SERVICE_PORT` in `config.py`).
- **ModelService_URL**: `http://localhost:<ModelService_Port>` — the base URL used by both the App and the Server to reach ModelService.
- **SpawningParent**: The process (App or Server) that first determines ModelService is not running and launches it as a child subprocess.
- **NetworkGPUStrategy**: The `NetworkGPUTranscriptionStrategy` class in `transcription_strategies.py` that delegates transcription to a remote HTTP server via HTTP POST to `/transcribe`.
- **LocalGPUStrategy**: The `LocalGPUTranscriptionStrategy` class in `transcription_strategies.py` that loads and runs the Whisper model in-process.
- **TranscriptionManager**: The `TranscriptionManager` class in `transcription_strategies.py` that selects and invokes the active transcription strategy.
- **HealthProbe**: An HTTP GET to `ModelService_URL/health` used to determine whether ModelService is already running.
- **ModelCompatibility**: The condition where ModelService reports the same Whisper model name as `WHISPER_MODEL` in `config.py`.
- **VRAM**: Video RAM on the GPU, the shared resource being conserved by this feature.

---

## Requirements

### Requirement 1: ModelService as a Spawnable Transcription Process

**User Story:** As a developer, I want a dedicated ModelService process that owns the Whisper model and serves transcription requests, so that neither the App nor the Server needs to load the model in-process when ModelService is available.

#### Acceptance Criteria

1. THE `ModelService` SHALL expose a `/health` endpoint that returns `{"status": "ok", "model": "<model_name>"}` with HTTP 200 when the Whisper model is loaded and ready.
2. THE `ModelService` SHALL expose a `/transcribe` endpoint that accepts raw WAV bytes via HTTP POST and returns `{"text": "<transcription>", "processing_time": <seconds>}` with HTTP 200 on success.
3. WHEN the Whisper model fails to load at startup, THE `ModelService` SHALL exit with a non-zero exit code and log the error before exiting.
4. THE `ModelService` SHALL accept `--port`, `--model`, and `--api-key` command-line arguments, consistent with the interface of `transcription_server.py`.
5. THE `ModelService` SHALL be launchable as a standalone process via `python model_service.py` for independent testing and use.
6. WHEN an optional Bearer token is configured via `--api-key`, THE `ModelService` SHALL enforce token authentication on the `/transcribe` endpoint and return HTTP 401 for unauthorized requests.

---

### Requirement 2: Spawn-or-Connect Logic at Startup

**User Story:** As a developer running both the App and the Server on the same GPU machine, I want whichever process starts first to automatically spawn ModelService, and the second process to simply connect to the already-running instance, so that only one Whisper model is ever loaded into GPU memory.

#### Acceptance Criteria

1. WHEN the App initializes the `TranscriptionManager` and `DEFAULT_TRANSCRIPTION_METHOD` is `"local"` or `"auto"`, THE `TranscriptionManager` SHALL perform a `HealthProbe` to `ModelService_URL` before loading the `LocalGPUStrategy`.
2. WHEN the Server starts up and `MODEL_SERVICE_ENABLED` is `True`, THE `Server` SHALL perform a `HealthProbe` to `ModelService_URL` before loading the `WhisperModel`.
3. WHEN the `HealthProbe` returns HTTP 200 with `{"status": "ok"}` and `ModelCompatibility` is confirmed, THE initiating process SHALL connect to the running ModelService via `NetworkGPUStrategy` and SHALL NOT spawn a new ModelService instance.
4. WHEN the `HealthProbe` fails (timeout, connection refused, or non-200 response), THE initiating process SHALL attempt to spawn ModelService as a child subprocess before proceeding.
5. WHEN ModelService is spawned, THE `SpawningParent` SHALL wait up to `MODEL_SERVICE_STARTUP_TIMEOUT` seconds for ModelService to become healthy (i.e., for a subsequent `HealthProbe` to succeed) before treating the spawn as failed.
6. THE `HealthProbe` SHALL complete within 2 seconds so that startup time is not materially affected.
7. WHEN `DEFAULT_TRANSCRIPTION_METHOD` is `"api"` or `"network_gpu"`, THE `TranscriptionManager` SHALL skip the `HealthProbe` and spawn logic entirely.

---

### Requirement 3: Model Compatibility Verification

**User Story:** As a developer, I want both the App and the Server to verify that ModelService is running the correct Whisper model before connecting to it, so that transcription quality is not silently degraded by a model mismatch.

#### Acceptance Criteria

1. WHEN a `HealthProbe` returns HTTP 200, THE initiating process SHALL compare the `model` field in the `/health` response against `WHISPER_MODEL` from `config.py`.
2. WHEN the model names match, THE initiating process SHALL treat ModelService as compatible and proceed to connect via `NetworkGPUStrategy`.
3. WHEN the model names do not match, THE initiating process SHALL log a WARNING including both the ModelService model name and the configured `WHISPER_MODEL`, and SHALL fall back to its default behavior (App loads `LocalGPUStrategy`; Server loads `WhisperModel` directly).
4. IF the `/health` response does not contain a `model` field, THEN THE initiating process SHALL treat ModelService as incompatible and fall back to its default behavior.

---

### Requirement 4: Transparent Strategy Substitution in the App

**User Story:** As a developer, I want the App to silently use ModelService when available, so that the rest of the application code requires no changes and the behavior is fully automatic.

#### Acceptance Criteria

1. WHEN ModelService is reachable and `ModelCompatibility` is confirmed, THE `TranscriptionManager` SHALL register and activate a `NetworkGPUStrategy` pointing to `ModelService_URL` as the primary strategy, in place of the `LocalGPUStrategy`.
2. WHEN the `NetworkGPUStrategy` is activated as a substitute for `LocalGPUStrategy`, THE `TranscriptionManager` SHALL NOT load the `LocalGPUStrategy` or instantiate a `WhisperModel` in-process.
3. THE `TranscriptionManager` SHALL log an INFO-level message when it substitutes `NetworkGPUStrategy` for `LocalGPUStrategy`, including the `ModelService_URL` being used.
4. WHEN the substitution occurs, THE App's existing fallback chain SHALL remain intact: if the `NetworkGPUStrategy` subsequently fails, THE `TranscriptionManager` SHALL fall back to the configured fallback strategy (e.g., Groq API) as normal.

---

### Requirement 5: Transparent Strategy Substitution in the Server

**User Story:** As a developer, I want the transcription Server to use ModelService when available instead of loading the Whisper model directly, so that the Server participates in the shared-model scheme regardless of which process started first.

#### Acceptance Criteria

1. WHEN ModelService is reachable and `ModelCompatibility` is confirmed at Server startup, THE `Server` SHALL forward all `/transcribe` requests to `ModelService_URL/transcribe` instead of loading the `WhisperModel` in-process.
2. WHEN the `Server` is using ModelService, THE `Server`'s own `/health` endpoint SHALL return `{"status": "ok", "model": "<MODEL_NAME>", "mode": "model_service", "model_service_url": "<ModelService_URL>"}`.
3. WHEN ModelService is unreachable or incompatible at Server startup, THE `Server` SHALL load the `WhisperModel` directly and operate normally, with no change to existing behavior.
4. WHEN a forwarded request from the `Server` to ModelService fails, THE `Server` SHALL return HTTP 502 to the caller and log a WARNING including the target URL and the error.

---

### Requirement 6: Fallback Behavior When ModelService Is Unavailable

**User Story:** As a developer, I want both the App and the Server to fall back to loading the model locally if ModelService cannot be started or becomes unavailable, so that transcription always works regardless of ModelService status.

#### Acceptance Criteria

1. WHEN the `SpawningParent` fails to spawn ModelService (process fails to start or does not become healthy within `MODEL_SERVICE_STARTUP_TIMEOUT`), THE `SpawningParent` SHALL log a WARNING and fall back to its default behavior (App loads `LocalGPUStrategy`; Server loads `WhisperModel` directly).
2. WHEN ModelService is unreachable at startup (and spawning is disabled or fails), THE App SHALL load the `LocalGPUStrategy` as normal, with no change to existing behavior.
3. WHEN the `NetworkGPUStrategy` pointing to ModelService returns a connection error during transcription, THE `TranscriptionManager` SHALL fall back to the next available strategy according to the existing fallback chain.
4. THE `TranscriptionManager` SHALL NOT attempt to dynamically reload the `LocalGPUStrategy` at runtime after startup; fallback is handled by the existing strategy chain.
5. IF `MODEL_SERVICE_ENABLED` is `False`, THEN THE App and Server SHALL skip all ModelService probe and spawn logic and behave as if this feature does not exist.

---

### Requirement 7: ModelService Lifecycle Management

**User Story:** As a developer, I want ModelService to be cleaned up automatically when the process that spawned it exits, so that orphaned ModelService processes do not accumulate on the machine.

#### Acceptance Criteria

1. WHEN the `SpawningParent` exits normally, THE `SpawningParent` SHALL terminate the ModelService subprocess before exiting.
2. WHEN the `SpawningParent` exits due to an unhandled exception or signal, THE `SpawningParent` SHALL attempt to terminate the ModelService subprocess as part of its cleanup handler.
3. WHEN a non-spawning process (the second process to connect) exits, THE ModelService subprocess SHALL continue running, as it is owned by the `SpawningParent`.
4. THE `SpawningParent` SHALL register an `atexit` handler (or equivalent) to ensure ModelService termination is attempted even if the parent exits unexpectedly.
5. WHEN ModelService is terminated by its parent, THE `SpawningParent` SHALL wait up to 5 seconds for the subprocess to exit cleanly before sending a forceful termination signal.

---

### Requirement 8: Configuration

**User Story:** As a developer, I want to control ModelService behavior through `config.py`, so that I can tune port, enable/disable the feature, and adjust timeouts without modifying source code.

#### Acceptance Criteria

1. THE `config.py` SHALL expose a boolean setting `MODEL_SERVICE_ENABLED` (default: `True`) that controls whether the ModelService probe and spawn logic is active.
2. THE `config.py` SHALL expose an integer setting `MODEL_SERVICE_PORT` (default: `8766`) that specifies the localhost port on which ModelService listens.
3. THE `config.py` SHALL expose a float setting `MODEL_SERVICE_STARTUP_TIMEOUT` (default: `30.0` seconds) that controls how long the `SpawningParent` waits for ModelService to become healthy after spawning.
4. WHEN `MODEL_SERVICE_ENABLED` is `False`, THE App and Server SHALL skip all ModelService probe and spawn logic and load the model in-process as before.
5. THE `config.py` SHALL expose an optional string setting `MODEL_SERVICE_API_KEY` (default: `None`) that is passed to ModelService as the `--api-key` argument when spawning, and used as the Bearer token when connecting.

---

### Requirement 9: Observability and Logging

**User Story:** As a developer, I want clear log output describing the ModelService detection and spawn outcome in both the App and the Server, so that I can diagnose startup behavior without attaching a debugger.

#### Acceptance Criteria

1. WHEN the ModelService probe and spawn logic is skipped (feature disabled or wrong transcription method), THE initiating process SHALL log a DEBUG-level message stating that ModelService integration was skipped and the reason.
2. WHEN ModelService is already running and is connected to, THE initiating process SHALL log an INFO-level message: `"ModelService already running at <url> (model: <model_name>) — connecting, skipping local model load"`.
3. WHEN ModelService is not running and is successfully spawned, THE `SpawningParent` SHALL log an INFO-level message: `"ModelService not found at <url> — spawning ModelService (pid: <pid>)"`.
4. WHEN ModelService fails to become healthy within `MODEL_SERVICE_STARTUP_TIMEOUT`, THE `SpawningParent` SHALL log a WARNING-level message: `"ModelService failed to start within <timeout>s — falling back to local model load"`.
5. WHEN a model mismatch is detected, THE initiating process SHALL log a WARNING-level message: `"ModelService model '<service_model>' differs from configured '<WHISPER_MODEL>' — falling back to local model load"`.
6. WHEN the `SpawningParent` terminates ModelService on exit, THE `SpawningParent` SHALL log an INFO-level message: `"Terminating ModelService subprocess (pid: <pid>)"`.
7. WHEN a forwarded request from the Server to ModelService fails, THE `Server` SHALL log a WARNING-level message including the target URL and the error.
