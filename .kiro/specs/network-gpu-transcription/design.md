# Design Document: Network GPU Transcription

## Overview

The Network GPU Transcription feature adds a third transcription strategy to the existing two-strategy system (Local GPU and Groq API). It enables a powerful GPU machine on the local network to act as a transcription server, while client machines send audio over HTTP for transcription.

The feature has two parts:

1. **`transcription_server.py`** — a standalone FastAPI server that runs on the GPU machine, loads faster-whisper at startup, and exposes `/transcribe` and `/health` endpoints.
2. **`NetworkGPUTranscriptionStrategy`** — a new strategy class in `transcription_strategies.py` that sends WAV bytes to the server and returns a `TranscriptionResult`, integrating transparently with the existing `TranscriptionManager`, fallback logic, and UI.

The design follows the same strategy pattern already established for `LocalGPUTranscriptionStrategy` and `GroqAPITranscriptionStrategy`, requiring minimal changes to existing code.

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Client Machine (weak/no GPU)                                   │
│                                                                 │
│  AudioCapture → audio_queue → transcription_thread             │
│                                    │                           │
│                          TranscriptionManager                  │
│                         ┌──────────┴──────────┐               │
│                    primary_strategy      fallback_strategy     │
│                         │                                      │
│              NetworkGPUTranscriptionStrategy                   │
│                         │                                      │
│                  HTTP POST /transcribe                         │
│                  (WAV bytes, Bearer token)                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │  LAN / localhost
┌─────────────────────────────▼───────────────────────────────────┐
│  GPU Machine                                                    │
│                                                                 │
│  transcription_server.py (FastAPI + uvicorn)                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  POST /transcribe  ←── WAV bytes                        │  │
│  │  GET  /health      ←── availability probe               │  │
│  │                                                          │  │
│  │  faster-whisper (large-v3, CUDA)                        │  │
│  │  hallucination filter (same as LocalGPUStrategy)        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Interaction

```
config.py
  NETWORK_GPU_SERVER_URL, NETWORK_GPU_TIMEOUT,
  NETWORK_GPU_ENABLED, NETWORK_GPU_API_KEY
        │
        ▼
transcription.py :: initialize_transcription_manager()
  if NETWORK_GPU_ENABLED:
    register NetworkGPUTranscriptionStrategy
        │
        ▼
transcription_strategies.py :: NetworkGPUTranscriptionStrategy
  transcribe()  → POST /transcribe → TranscriptionResult
  is_available() → GET /health (cached 10s)
        │
        ▼
ui_view.py :: _create_transcription_method_selector()
  ttk.OptionMenu showing only available strategies
```

---

## Components and Interfaces

### 1. `transcription_server.py` (new file, project root)

A standalone FastAPI application. It is not imported by the client — it runs as a separate process on the GPU machine.

**Startup sequence:**
1. Parse CLI args (`--host`, `--port`, `--model`, `--api-key`)
2. Load faster-whisper model using config constants
3. If model load fails → log error, `sys.exit(1)`
4. Start uvicorn on the configured host/port
5. Log bound address and model name

**Endpoints:**

| Method | Path | Auth required | Description |
|--------|------|---------------|-------------|
| `POST` | `/transcribe` | If `--api-key` set | Accept raw WAV bytes, return transcription JSON |
| `GET` | `/health` | Never | Return model readiness status |

**`POST /transcribe` contract:**

Request:
```
Content-Type: application/octet-stream
Authorization: Bearer <token>   (if --api-key configured)
Body: <raw WAV bytes>
```

Response (200 OK):
```json
{"text": "Hello world", "processing_time": 1.23}
```

Response (200 OK, empty audio):
```json
{"text": "", "processing_time": 0.01}
```

Response (500 Internal Server Error):
```json
{"detail": "Transcription failed: <reason>"}
```

Response (401 Unauthorized, bad/missing token):
```json
{"detail": "Unauthorized"}
```

**`GET /health` contract:**

Response (200 OK, model ready):
```json
{"status": "ok", "model": "large-v3"}
```

Response (503 Service Unavailable, model not ready):
```json
{"status": "unavailable", "reason": "Model not loaded"}
```

**Auth middleware:**
- If `--api-key` is provided at startup, a FastAPI dependency checks every request (except `/health`) for `Authorization: Bearer <token>`.
- Mismatch or missing header → HTTP 401.
- `/health` is always unauthenticated so clients can probe availability without credentials.

**Hallucination filter** (identical to `LocalGPUTranscriptionStrategy`):
```python
lt = cleaned_text.casefold()
if (("thank" in lt or "subtitles" in lt or "captions" in lt) and len(cleaned_text) <= 40) \
        or len(cleaned_text) <= 10:
    result_text = ""
```

**CLI interface:**
```
python transcription_server.py [--host HOST] [--port PORT] [--model MODEL] [--api-key KEY]

Defaults:
  --host    0.0.0.0
  --port    8765
  --model   value of WHISPER_MODEL from config.py
  --api-key (none — auth disabled)
```

---

### 2. `NetworkGPUTranscriptionStrategy` (added to `transcription_strategies.py`)

Implements `TranscriptionStrategy` ABC. Does **not** load any local ML models.

```python
class NetworkGPUTranscriptionStrategy(TranscriptionStrategy):
    def get_name(self) -> str: ...          # returns "Network GPU"
    def transcribe(self, audio_segment) -> TranscriptionResult: ...
    def is_available(self) -> bool: ...     # cached 10s health check
```

**`transcribe()` flow:**
1. Call `audio_segment.get_wav_bytes()` to get raw WAV bytes
2. Build headers: `Content-Type: application/octet-stream`; add `Authorization: Bearer {NETWORK_GPU_API_KEY}` if key is set
3. `requests.post(f"{NETWORK_GPU_SERVER_URL}/transcribe", data=wav_bytes, headers=headers, timeout=NETWORK_GPU_TIMEOUT)`
4. On HTTP 200 → parse JSON, return `TranscriptionResult(text=..., method_used="network_gpu", ...)`
5. On HTTP 4xx/5xx → return `TranscriptionResult(text="", error_message="HTTP {status}: {body}", ...)`
6. On `requests.ConnectionError` / `requests.Timeout` → return `TranscriptionResult(text="", error_message="Connection failed: ...", ...)`
7. Never raises — all errors are captured in `error_message`

**`is_available()` flow:**
1. Check cache: if last check was < 10 seconds ago, return cached result
2. `requests.get(f"{NETWORK_GPU_SERVER_URL}/health", timeout=3.0)`
3. Return `True` if HTTP 200 and `response.json().get("status") == "ok"`
4. Return `False` on any exception or non-200 response
5. Cache result with timestamp

---

### 3. Config additions (`config.py`)

```python
# Network GPU Transcription
NETWORK_GPU_SERVER_URL = "http://localhost:8765"
NETWORK_GPU_TIMEOUT    = 30.0
NETWORK_GPU_ENABLED    = False
NETWORK_GPU_API_KEY    = None   # Optional Bearer token; None = auth disabled
```

`DEFAULT_TRANSCRIPTION_METHOD` gains `"network_gpu"` as a valid value.

`validate_transcription_config()` is extended:
- Adds `"network_gpu_enabled"` key to results
- Adds `"network_gpu_server_url"` key to results
- When `NETWORK_GPU_ENABLED` is `True` and `NETWORK_GPU_SERVER_URL` is empty → error
- When `DEFAULT_TRANSCRIPTION_METHOD == "network_gpu"` and `NETWORK_GPU_ENABLED` is `False` → warning
- Valid methods list becomes `["local", "api", "auto", "network_gpu"]`

---

### 4. `transcription.py` changes

**`initialize_transcription_manager()`** — add after Groq strategy block:
```python
from config import NETWORK_GPU_ENABLED
if NETWORK_GPU_ENABLED:
    try:
        from transcription_strategies import NetworkGPUTranscriptionStrategy
        net_config = StrategyConfig(
            name="network_gpu", enabled=True, priority=3,
            timeout=NETWORK_GPU_TIMEOUT, retry_count=0, specific_config={}
        )
        net_strategy = NetworkGPUTranscriptionStrategy(net_config)
        manager.register_strategy(net_strategy)
    except Exception as e:
        logger.warning(f"Failed to initialize Network GPU strategy: {e}")
```

**`switch_transcription_method()`** — add to `strategy_mapping`:
```python
"network_gpu": "Network GPU",
"network": "Network GPU",
```

**Primary strategy selection** — add `"network_gpu"` branch parallel to existing `"local"` / `"api"` branches.

**`_handle_transcription_error()`** — add branch:
```python
elif "connection failed" in error_lower or ("network" in error_lower and "gpu" in error_lower):
    exception_notifier.notify_exception("transcription", error_exception, "warning",
                                        "Network GPU unreachable - Check server")
```

---

### 5. UI changes (`ui_view.py`)

Replace the binary checkbox approach with a `ttk.OptionMenu` dropdown that mirrors the existing Auto-Submit pattern.

**Remove:**
- `_create_transcription_method_toggle_title_level()`
- `update_transcription_method_control(gpu_available, api_available, current_method)`
- `get_transcription_method_preference() -> bool`
- `self.transcription_method_var = tk.BooleanVar(...)`
- `self.transcription_method_checkbox`

**Add:**

```python
def _create_transcription_method_selector(self):
    """Create transcription method dropdown at title level of Topics frame."""
    self.transcription_method_var = tk.StringVar(value="")
    self.transcription_method_menu = ttk.OptionMenu(
        self.list_frame,
        self.transcription_method_var,
        "",          # initial placeholder; rebuilt by update_transcription_method_control
        command=self.controller.on_transcription_method_change
    )
    self.transcription_method_menu.place(
        relx=1.0, rely=0.0, anchor="ne", x=-10, y=-25
    )
    self.transcription_method_menu.place_forget()   # hidden until controller shows it

def update_transcription_method_control(
        self,
        available_methods: dict,   # {display_name: bool}  e.g. {"Local GPU": True, "Network GPU": False}
        current_method: str        # display name of active strategy
):
    """Rebuild dropdown options from available strategies."""
    enabled = [name for name, avail in available_methods.items() if avail]
    if not enabled:
        self.transcription_method_menu.place_forget()
        return

    menu = self.transcription_method_menu["menu"]
    menu.delete(0, "end")
    for name in enabled:
        menu.add_command(
            label=name,
            command=lambda n=name: (
                self.transcription_method_var.set(n),
                self.controller.on_transcription_method_change(n)
            )
        )

    if current_method in enabled:
        self.transcription_method_var.set(current_method)
    elif enabled:
        self.transcription_method_var.set(enabled[0])

    state = "disabled" if len(enabled) == 1 else "normal"
    self.transcription_method_menu.config(state=state)
    self.transcription_method_menu.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=-25)

def get_transcription_method_preference(self) -> str:
    """Return the currently selected method display name."""
    return self.transcription_method_var.get()
```

**`_create_status_bar()`** — add to `status_colors`:
```python
"transcription_network_gpu": ("#006400", "Transcription: Network GPU"),
```

**`update_transcription_status()`** — extend method detection:
```python
elif "network" in method_lower or "network_gpu" in method_lower:
    status_key = "transcription_network_gpu"
```

**`create_widgets()`** — replace call to `_create_transcription_method_toggle_title_level()` with `_create_transcription_method_selector()`.

---

### 6. Dependencies (`requirements.in`)

Add:
```
fastapi
uvicorn[standard]
requests
```

`requests` may already be present transitively; add explicitly for clarity.

---

## Data Models

### `TranscriptionResult` (existing, unchanged)

```python
@dataclass
class TranscriptionResult:
    text: str
    method_used: str        # "network_gpu" for this strategy
    processing_time: float
    fallback_used: bool
    error_message: Optional[str] = None
    timestamp: datetime = None
```

### Server request/response shapes

**POST /transcribe**

| Field | Type | Notes |
|-------|------|-------|
| request body | `bytes` | Raw WAV bytes, `Content-Type: application/octet-stream` |
| `text` | `str` | Transcription result (empty string if silence/filtered) |
| `processing_time` | `float` | Seconds taken by faster-whisper |

**GET /health**

| Field | Type | Notes |
|-------|------|-------|
| `status` | `str` | `"ok"` or `"unavailable"` |
| `model` | `str` | Model name (only when `status == "ok"`) |
| `reason` | `str` | Error description (only when `status == "unavailable"`) |

### Availability cache (in-memory, per `NetworkGPUTranscriptionStrategy` instance)

```python
_availability_cache: Optional[bool] = None
_availability_cache_time: Optional[float] = None   # time.monotonic()
AVAILABILITY_CACHE_TTL = 10.0  # seconds
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Round-trip audio fidelity

*For any* valid `AudioSegment`, transcribing it locally with `LocalGPUTranscriptionStrategy` and transcribing it via `NetworkGPUTranscriptionStrategy` (pointing at a server running the same model and parameters) should produce equivalent text results.

**Validates: Requirements 12.1, 12.2, 12.3**

---

### Property 2: Hallucination filter consistency

*For any* audio payload, the text returned by `POST /transcribe` should never contain a string that would have been filtered by the hallucination filter in `LocalGPUTranscriptionStrategy` (i.e., the server applies the same filter).

**Validates: Requirements 1.5**

---

### Property 3: Health check availability contract

*For any* `NetworkGPUTranscriptionStrategy` instance, if `is_available()` returns `True`, then a subsequent call to `transcribe()` with a valid audio segment should not return a connection-error result (within the same cache window).

**Validates: Requirements 5.1, 5.2, 5.3**

---

### Property 4: Availability caching

*For any* sequence of `is_available()` calls made within 10 seconds of each other, all calls should return the same cached value without issuing additional HTTP requests.

**Validates: Requirements 5.5**

---

### Property 5: Error containment

*For any* network failure (connection refused, timeout, DNS error), `transcribe()` should return a `TranscriptionResult` with `text == ""` and a non-empty `error_message`, and should never raise an exception.

**Validates: Requirements 4.5, 10.3**

---

### Property 6: Auth enforcement

*For any* request to `POST /transcribe` or `POST /transcribe` when the server is started with `--api-key`, a request missing or presenting an incorrect `Authorization: Bearer` token should receive HTTP 401, and a request with the correct token should receive HTTP 200.

**Validates: Requirements 11.1, 11.2, 11.3**

---

### Property 7: Empty audio handling

*For any* zero-length or silence-only WAV payload sent to `POST /transcribe`, the server should return HTTP 200 with `{"text": ""}` and never return a 500 error.

**Validates: Requirements 1.3**

---

### Property 8: Strategy registration gating

*For any* configuration where `NETWORK_GPU_ENABLED = False`, calling `initialize_transcription_manager()` should result in a `TranscriptionManager` that does not contain a `"Network GPU"` strategy in `get_available_strategies()`.

**Validates: Requirements 6.5**

---

## Error Handling

### Error handling matrix

| Scenario | Where handled | Behavior |
|----------|--------------|----------|
| Server not running at startup | `is_available()` | Returns `False`; strategy not set as primary |
| Server goes down mid-session | `transcribe()` catches `ConnectionError` | Returns error result; `TranscriptionManager` activates fallback |
| Request timeout | `transcribe()` catches `Timeout` | Returns error result with descriptive message |
| HTTP 401 (bad API key) | `transcribe()` checks status code | Returns error result; logs auth failure |
| HTTP 500 from server | `transcribe()` checks status code | Returns error result with server error body |
| faster-whisper fails on server | Server returns HTTP 500 | Client receives error result |
| faster-whisper fails at server startup | Server logs and `sys.exit(1)` | Server never becomes healthy; `is_available()` returns `False` |
| No fallback configured + server down | `TranscriptionManager._attempt_fallback()` | Returns primary error result with empty text |
| `NETWORK_GPU_ENABLED = False` | `initialize_transcription_manager()` | Strategy never registered; no network calls made |

### Fallback integration

The `NetworkGPUTranscriptionStrategy` integrates with the existing fallback mechanism without any changes to `TranscriptionManager`. When `transcribe()` returns a result with a non-None `error_message`, `transcribe_with_fallback()` already calls `_attempt_fallback()`. The audio segment is re-queued by `transcription_thread` on error, consistent with existing behavior.

### Server startup failure

```
python transcription_server.py
→ loads model
→ if ImportError or model load exception:
    logger.error(...)
    sys.exit(1)
→ else:
    logger.info(f"Server ready on {host}:{port}, model={model_name}")
    uvicorn.run(app, ...)
```

---

## Testing Strategy

### Unit tests

Focus on specific examples, edge cases, and error conditions that are hard to cover with property tests:

- `NetworkGPUTranscriptionStrategy.transcribe()` with mocked `requests.post` returning 200, 401, 500, `ConnectionError`, `Timeout`
- `NetworkGPUTranscriptionStrategy.is_available()` cache behavior: two calls within 10s should only issue one HTTP request
- `initialize_transcription_manager()` with `NETWORK_GPU_ENABLED=False` → strategy absent
- `initialize_transcription_manager()` with `NETWORK_GPU_ENABLED=True` → strategy present
- `switch_transcription_method("network_gpu")` maps correctly
- `validate_transcription_config()` with `NETWORK_GPU_ENABLED=True` and empty URL → error
- Server: `POST /transcribe` with valid WAV → 200 + JSON
- Server: `GET /health` before model loaded → 503
- Server: `GET /health` after model loaded → 200
- Server: `POST /transcribe` without token when `--api-key` set → 401
- Server: `POST /transcribe` with correct token → 200
- UI: `update_transcription_method_control` with one available method → dropdown disabled
- UI: `update_transcription_method_control` with three available methods → dropdown enabled with three options

### Property-based tests

Use `hypothesis` (already available in the Python ecosystem). Each test runs a minimum of 100 iterations.

**Property 1: Round-trip audio fidelity**
```
# Feature: network-gpu-transcription, Property 1: round-trip audio fidelity
@given(audio_segment=st.builds(...))
def test_round_trip_fidelity(audio_segment):
    local_result = local_strategy.transcribe(audio_segment)
    network_result = network_strategy.transcribe(audio_segment)
    assert local_result.text == network_result.text
```
*Note: requires a live server; run as integration test.*

**Property 2: Hallucination filter consistency**
```
# Feature: network-gpu-transcription, Property 2: hallucination filter consistency
@given(text=st.text())
def test_hallucination_filter_matches_local(text):
    server_filtered = server_filter(text)
    local_filtered = local_filter(text)
    assert server_filtered == local_filtered
```

**Property 3: Health check availability contract**
```
# Feature: network-gpu-transcription, Property 3: health check availability contract
@given(audio=valid_audio_segments())
def test_available_then_transcribe_no_connection_error(audio):
    if strategy.is_available():
        result = strategy.transcribe(audio)
        assert "connection" not in (result.error_message or "").lower()
```

**Property 4: Availability caching**
```
# Feature: network-gpu-transcription, Property 4: availability caching
@given(n=st.integers(min_value=2, max_value=20))
def test_availability_cache(n, mock_requests):
    for _ in range(n):
        strategy.is_available()
    assert mock_requests.get.call_count == 1
```

**Property 5: Error containment**
```
# Feature: network-gpu-transcription, Property 5: error containment
@given(audio=valid_audio_segments(), error=connection_errors())
def test_transcribe_never_raises(audio, error, mock_requests):
    mock_requests.post.side_effect = error
    result = strategy.transcribe(audio)
    assert result.text == ""
    assert result.error_message is not None
```

**Property 6: Auth enforcement**
```
# Feature: network-gpu-transcription, Property 6: auth enforcement
@given(token=st.text(min_size=1))
def test_wrong_token_returns_401(token, test_client, correct_key):
    assume(token != correct_key)
    resp = test_client.post("/transcribe", content=b"...",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
```

**Property 7: Empty audio handling**
```
# Feature: network-gpu-transcription, Property 7: empty audio handling
@given(payload=st.binary(max_size=0) | silence_wav_bytes())
def test_empty_audio_returns_200(payload, test_client):
    resp = test_client.post("/transcribe", content=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == ""
```

**Property 8: Strategy registration gating**
```
# Feature: network-gpu-transcription, Property 8: strategy registration gating
@given(enabled=st.just(False))
def test_disabled_strategy_not_registered(enabled, monkeypatch):
    monkeypatch.setattr(config, "NETWORK_GPU_ENABLED", enabled)
    manager = initialize_transcription_manager()
    assert "Network GPU" not in manager.get_available_strategies()
```

### Integration tests

- Start `transcription_server.py` as a subprocess on a random port; run client strategy against it; verify round-trip fidelity with a known WAV fixture.
- Verify fallback activates when server is stopped mid-session.
- Verify UI dropdown shows/hides "Network GPU" based on `NETWORK_GPU_ENABLED` and server reachability.
