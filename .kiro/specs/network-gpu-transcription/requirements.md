# Requirements Document

## Introduction

The Network GPU Transcription feature adds a third transcription mode to the existing two-strategy system (Local GPU and Groq API). It enables a powerful GPU machine on the local network to act as a transcription server, while client machines (with weak or no GPU) send audio to it over HTTP for transcription. This allows teams to share a single high-performance transcription resource across multiple client machines without requiring cloud API access.

The feature consists of two parts:
1. A **transcription server** (`transcription_server.py`) that runs on the GPU machine, loads faster-whisper, and exposes an HTTP API
2. A **client strategy** (`NetworkGPUTranscriptionStrategy`) added to `transcription_strategies.py` that sends audio to the server and returns results

The new strategy integrates cleanly with the existing `TranscriptionManager`, strategy pattern, fallback system, and UI controls.

## Glossary

- **Transcription_Server**: The FastAPI HTTP server process running on the GPU machine, exposing transcription endpoints
- **Network_GPU_Strategy**: The `NetworkGPUTranscriptionStrategy` client class that sends audio to the Transcription_Server
- **Transcription_Manager**: The existing `TranscriptionManager` class that manages strategy selection and fallback
- **Audio_Segment**: The existing `AudioSegment` object containing raw audio data and metadata
- **Transcription_Result**: The existing `TranscriptionResult` dataclass returned by all strategies
- **Health_Check**: A lightweight HTTP GET request to `/health` used to verify server reachability
- **Server_URL**: The base URL of the Transcription_Server, e.g. `http://192.168.1.100:8765`
- **WAV_Bytes**: Raw WAV-formatted audio bytes as produced by `AudioSegment.get_wav_bytes()`
- **Strategy_Config**: The existing `StrategyConfig` dataclass used to configure any transcription strategy

---

## Requirements

### Requirement 1: Transcription Server — Core Transcription Endpoint

**User Story:** As a user running the app on a weak/no-GPU machine, I want a server on my GPU machine to handle transcription, so that I get fast local-quality transcription without needing a local GPU.

#### Acceptance Criteria

1. THE Transcription_Server SHALL expose a `POST /transcribe` HTTP endpoint that accepts a request body containing raw WAV_Bytes
2. WHEN a valid WAV_Bytes payload is received, THE Transcription_Server SHALL transcribe the audio using faster-whisper and return a JSON response containing the transcription text and processing time
3. WHEN an empty or zero-length audio payload is received, THE Transcription_Server SHALL return a JSON response with an empty transcription text and no error
4. IF the faster-whisper model fails to transcribe the audio, THEN THE Transcription_Server SHALL return a JSON error response with an HTTP 500 status code and a descriptive error message
5. THE Transcription_Server SHALL apply the same hallucination filtering logic used by `LocalGPUTranscriptionStrategy` (filtering short results and known junk phrases)
6. THE Transcription_Server SHALL log each transcription request including audio size, processing time, and result length

### Requirement 2: Transcription Server — Startup and Configuration

**User Story:** As a developer on the GPU machine, I want to start the transcription server with a simple command, so that I can make it available to client machines on the network.

#### Acceptance Criteria

1. THE Transcription_Server SHALL be runnable as a standalone script via `python transcription_server.py`
2. WHEN started, THE Transcription_Server SHALL load the faster-whisper model using the same `WHISPER_MODEL`, `COMPUTE_TYPE`, `MODELS_FOLDER`, `LANGUAGE`, and `BEAM_SIZE` constants from `config.py`
3. WHEN started, THE Transcription_Server SHALL bind to a configurable host and port, defaulting to `0.0.0.0` and port `8765`
4. THE Transcription_Server SHALL accept `--host`, `--port`, and `--model` command-line arguments to override defaults at startup
5. WHEN the faster-whisper model fails to load at startup, THE Transcription_Server SHALL log the error and exit with a non-zero exit code
6. THE Transcription_Server SHALL log its bound address and loaded model name upon successful startup

### Requirement 3: Transcription Server — Health Check Endpoint

**User Story:** As a client machine, I want to check if the transcription server is reachable and ready before sending audio, so that I can detect availability and trigger fallback when the server is down.

#### Acceptance Criteria

1. THE Transcription_Server SHALL expose a `GET /health` HTTP endpoint
2. WHEN the faster-whisper model is loaded and ready, THE Transcription_Server SHALL respond to `GET /health` with HTTP 200 and a JSON body containing `{"status": "ok", "model": "<model_name>"}`
3. WHEN the faster-whisper model is not yet loaded or has failed, THE Transcription_Server SHALL respond to `GET /health` with HTTP 503 and a JSON body containing `{"status": "unavailable", "reason": "<description>"}`
4. THE Transcription_Server SHALL respond to `GET /health` within 2 seconds under normal operating conditions

### Requirement 4: Network GPU Client Strategy

**User Story:** As a client machine user, I want a transcription strategy that sends audio to the network GPU server, so that it works transparently within the existing transcription pipeline.

#### Acceptance Criteria

1. THE Network_GPU_Strategy SHALL implement the `TranscriptionStrategy` abstract base class with `transcribe()`, `is_available()`, and `get_name()` methods
2. WHEN `transcribe()` is called, THE Network_GPU_Strategy SHALL send the audio as WAV_Bytes in an HTTP POST request to `{Server_URL}/transcribe` and return a `Transcription_Result`
3. THE Network_GPU_Strategy SHALL set `method_used` to `"network_gpu"` in all returned `Transcription_Result` objects
4. WHEN the server returns a successful response, THE Network_GPU_Strategy SHALL populate `Transcription_Result.text` with the transcription text from the response
5. IF the HTTP request fails due to a connection error or timeout, THEN THE Network_GPU_Strategy SHALL return a `Transcription_Result` with an empty text and a descriptive `error_message`, without raising an exception
6. IF the server returns an HTTP error status (4xx or 5xx), THEN THE Network_GPU_Strategy SHALL return a `Transcription_Result` with an empty text and an `error_message` containing the HTTP status code and response body
7. THE Network_GPU_Strategy SHALL use the configured `NETWORK_GPU_TIMEOUT` value as the HTTP request timeout

### Requirement 5: Network GPU Client Strategy — Availability Detection

**User Story:** As the transcription system, I want to know whether the network GPU server is reachable before selecting it as the active strategy, so that unavailable servers don't block transcription.

#### Acceptance Criteria

1. WHEN `is_available()` is called, THE Network_GPU_Strategy SHALL perform a `GET /health` HTTP request to the configured Server_URL
2. WHEN the health check returns HTTP 200 with `{"status": "ok"}`, THE Network_GPU_Strategy SHALL return `True` from `is_available()`
3. WHEN the health check fails due to a connection error, timeout, or non-200 response, THE Network_GPU_Strategy SHALL return `False` from `is_available()`
4. THE Network_GPU_Strategy SHALL complete the `is_available()` check within 3 seconds by using a short connection timeout
5. THE Network_GPU_Strategy SHALL cache the availability result for 10 seconds to avoid excessive health check requests during rapid polling

### Requirement 6: Configuration

**User Story:** As a user, I want to configure the network GPU server URL and related settings in `config.py`, so that the client knows where to find the server.

#### Acceptance Criteria

1. THE System SHALL define `NETWORK_GPU_SERVER_URL` in `config.py` with a default value of `"http://localhost:8765"`
2. THE System SHALL define `NETWORK_GPU_TIMEOUT` in `config.py` with a default value of `30.0` seconds
3. THE System SHALL define `NETWORK_GPU_ENABLED` in `config.py` as a boolean with a default value of `False`
4. THE System SHALL define `"network_gpu"` as a valid value for `DEFAULT_TRANSCRIPTION_METHOD` in `config.py`
5. WHEN `NETWORK_GPU_ENABLED` is `False`, THE Transcription_Manager SHALL NOT register or attempt to initialize the Network_GPU_Strategy
6. THE `validate_transcription_config()` function SHALL include `NETWORK_GPU_ENABLED` and `NETWORK_GPU_SERVER_URL` in its validation output

### Requirement 7: Integration with TranscriptionManager

**User Story:** As the transcription system, I want the network GPU strategy to integrate with the existing manager, fallback, and switching logic, so that it behaves identically to the other two strategies.

#### Acceptance Criteria

1. WHEN `NETWORK_GPU_ENABLED` is `True` and the Network_GPU_Strategy is available, THE `initialize_transcription_manager()` function SHALL register the Network_GPU_Strategy with the Transcription_Manager
2. WHEN `DEFAULT_TRANSCRIPTION_METHOD` is `"network_gpu"`, THE `initialize_transcription_manager()` function SHALL set the Network_GPU_Strategy as the primary strategy
3. THE `switch_transcription_method()` function SHALL accept `"network_gpu"` as a valid method name and map it to the Network_GPU_Strategy
4. WHEN the Network_GPU_Strategy is the primary strategy and a transcription fails, THE Transcription_Manager SHALL attempt fallback to the configured fallback strategy using the existing fallback logic
5. THE `get_available_transcription_methods()` function SHALL include the Network_GPU_Strategy in its results when it is registered

### Requirement 8: UI — Method Selection

**User Story:** As a user, I want to select the network GPU transcription method from the UI, so that I can switch to it without editing config files.

#### Acceptance Criteria

1. WHEN the Network_GPU_Strategy is registered and available, THE UI SHALL display a transcription method selector that includes "Network GPU" as an option alongside "Local GPU" and "Groq API"
2. WHEN the user selects "Network GPU" in the UI, THE UI SHALL call the controller to switch the active strategy to the Network_GPU_Strategy
3. WHEN the Network_GPU_Strategy is unavailable (server unreachable), THE UI SHALL display the "Network GPU" option as disabled or grayed out
4. THE UI SHALL update the status bar to show "Transcription: Network GPU" when the Network_GPU_Strategy is the active strategy
5. WHEN the Network_GPU_Strategy is the only available method, THE UI SHALL display it as the sole active option without allowing switching

### Requirement 9: UI — Status and Error Feedback

**User Story:** As a user, I want the UI to show me when the network GPU server is unreachable or when transcription fails, so that I can take corrective action.

#### Acceptance Criteria

1. WHEN a transcription attempt via the Network_GPU_Strategy fails due to a connection error, THE UI SHALL display a status bar message indicating the server is unreachable
2. WHEN the Transcription_Manager activates fallback from the Network_GPU_Strategy, THE UI SHALL display a fallback notification consistent with existing fallback status messages
3. THE `status_colors` dictionary in `UIView` SHALL include a `"transcription_network_gpu"` entry with an appropriate color for the network GPU active state

### Requirement 10: Error Handling and Resilience

**User Story:** As a user, I want the system to handle network errors gracefully, so that a temporarily unreachable server doesn't crash the app or lose audio.

#### Acceptance Criteria

1. IF the network GPU server becomes unreachable during an active transcription session, THEN THE Transcription_Manager SHALL activate the fallback strategy using the existing fallback mechanism
2. IF no fallback strategy is configured and the network GPU server is unreachable, THEN THE Transcription_Manager SHALL return a `Transcription_Result` with an empty text and a descriptive `error_message`
3. WHEN a transcription request to the server times out, THE Network_GPU_Strategy SHALL treat the timeout as a connection failure and return an error result without retrying
4. THE Network_GPU_Strategy SHALL NOT load any local ML models; all inference SHALL occur on the Transcription_Server
5. FOR ALL audio segments that fail transcription via the Network_GPU_Strategy, THE transcription thread SHALL re-queue the audio segment for retry, consistent with the existing retry behavior in `transcription.py`

### Requirement 11: Security on Local Network

**User Story:** As a user deploying the server on a local network, I want basic protection against unintended access, so that the server is not trivially accessible from outside the intended network.

#### Acceptance Criteria

1. THE Transcription_Server SHALL accept an optional `--api-key` command-line argument to enable token-based authentication
2. WHERE `--api-key` is configured, THE Transcription_Server SHALL require all requests to include an `Authorization: Bearer <token>` header and SHALL return HTTP 401 for requests missing or presenting an incorrect token
3. WHERE `--api-key` is configured, THE Network_GPU_Strategy SHALL include the configured `NETWORK_GPU_API_KEY` value as an `Authorization: Bearer <token>` header in all requests
4. THE System SHALL define `NETWORK_GPU_API_KEY` in `config.py` with a default value of `None` (authentication disabled)
5. WHERE `--api-key` is NOT configured, THE Transcription_Server SHALL accept all requests without authentication, suitable for trusted local network deployments

### Requirement 12: Round-Trip Audio Fidelity

**User Story:** As a developer, I want to verify that audio sent over the network produces equivalent transcription results to local processing, so that I can trust the network path doesn't corrupt audio.

#### Acceptance Criteria

1. THE Network_GPU_Strategy SHALL transmit audio using `AudioSegment.get_wav_bytes()`, the same method used by `LocalGPUTranscriptionStrategy`
2. THE Transcription_Server SHALL accept the WAV_Bytes payload and pass it directly to faster-whisper using the same transcription parameters (`LANGUAGE`, `BEAM_SIZE`, `word_timestamps=False`) as `LocalGPUTranscriptionStrategy`
3. FOR ALL valid Audio_Segment objects, transcribing locally and transcribing via the network SHALL produce equivalent text results when using the same faster-whisper model and parameters (round-trip equivalence property)
