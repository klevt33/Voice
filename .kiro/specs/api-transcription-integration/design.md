# Design Document

## Overview

The API Transcription Integration feature extends the existing audio transcription processor with cloud-based transcription capabilities through the Groq Whisper API. The design maintains the existing architecture while adding a new transcription service layer that can seamlessly switch between local GPU processing and cloud API services.

The system employs a strategy pattern for transcription methods, allowing runtime switching without disrupting the audio processing pipeline. It includes intelligent fallback mechanisms, comprehensive error handling, and maintains the same data flow and quality standards as the existing local transcription system.

## Architecture

### High-Level Architecture Enhancement

The integration adds a new **Transcription Strategy Layer** between the existing audio processing and the transcription engine:

```
Audio Sources → Audio Queue → Transcription Strategy Router → [Local GPU | Groq API] → Topic Queue
```

### Component Integration Points

1. **Configuration Layer**: Extended to include API credentials and transcription method preferences
2. **UI Layer**: Enhanced with transcription method selection controls and status indicators
3. **Transcription Layer**: Refactored to support multiple transcription strategies
4. **Error Handling Layer**: Extended with API-specific error handling and fallback logic

### Threading Model Enhancement

The existing threading model is preserved with these additions:
- **Transcription Thread**: Enhanced to support strategy switching
- **API Request Management**: Asynchronous API calls within the existing transcription thread
- **Fallback Coordination**: Managed within the transcription thread to maintain thread safety

## Components and Interfaces

### Transcription Strategy Interface

**Abstract Base Class: `TranscriptionStrategy`**
```python
class TranscriptionStrategy(ABC):
    @abstractmethod
    def transcribe(self, audio_segment: AudioSegment) -> str:
        """Transcribe audio segment and return text"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if transcription method is available"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get strategy name for logging/UI"""
        pass
```

### Local GPU Transcription Strategy

**Class: `LocalGPUTranscriptionStrategy`**

**Responsibilities:**
- Wraps existing faster-whisper functionality
- Maintains GPU/CPU detection and optimization
- Provides consistent interface for local transcription

**Key Features:**
- CUDA availability detection
- Model caching and management
- Performance monitoring
- Resource cleanup

### Groq API Transcription Strategy

**Class: `GroqAPITranscriptionStrategy`**

**Responsibilities:**
- Groq API client management
- Audio format conversion for API requirements
- API error handling and retry logic
- Rate limiting and quota management

**Key Features:**
- Environment variable-based API key management
- WAV format conversion using existing AudioSegment methods
- Configurable timeout and retry parameters
- API response parsing and validation

**API Integration Details:**
```python
# Groq client initialization
client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Transcription request
transcription = client.audio.transcriptions.create(
    file=("audio.wav", audio_bytes),
    model="whisper-large-v3",
    response_format="verbose_json",
    language="en"
)
```

### Transcription Manager

**Class: `TranscriptionManager`**

**Responsibilities:**
- Strategy selection and switching coordination
- Fallback mechanism implementation
- Performance monitoring and logging
- Thread-safe strategy switching

**Key Methods:**
- `set_primary_strategy(strategy: TranscriptionStrategy)`
- `set_fallback_strategy(strategy: TranscriptionStrategy)`
- `transcribe_with_fallback(audio_segment: AudioSegment) -> str`
- `switch_strategy(new_strategy: str) -> bool`

**Fallback Logic:**
1. Attempt transcription with primary strategy
2. On failure, log error and attempt fallback strategy
3. Implement exponential backoff for repeated failures
4. Return to primary strategy when it recovers

### Configuration Enhancement

**Extended Configuration in `config.py`:**
```python
# API Transcription Configuration
GROQ_API_KEY_ENV_VAR = "GROQ_API_KEY"
GROQ_MODEL = "whisper-large-v3"
API_REQUEST_TIMEOUT = 30.0
API_RETRY_COUNT = 3
API_RETRY_BACKOFF = 2.0

# Transcription Method Configuration
DEFAULT_TRANSCRIPTION_METHOD = "auto"  # "local", "api", "auto"
ENABLE_FALLBACK = True
FALLBACK_RETRY_LIMIT = 3
FALLBACK_COOLDOWN_PERIOD = 60.0  # seconds
```

### UI Enhancement

**Enhanced UI Controls:**

1. **Transcription Method Checkbox**
   - Visible when both GPU and API are available
   - Disabled/grayed when only one method is available
   - Real-time switching capability

2. **Status Indicators**
   - Current transcription method indicator
   - Fallback event notifications
   - API rate limit warnings
   - Error state displays

**UI Integration Points:**
```python
# In ui_view.py - new transcription method control
def _create_transcription_method_control(self, parent):
    self.transcription_method_var = tk.BooleanVar(value=False)  # False=Local, True=API
    self.transcription_method_checkbox = ttk.Checkbutton(
        parent, 
        text="Use API Transcription", 
        variable=self.transcription_method_var,
        command=self.controller.on_transcription_method_change
    )
```

### Error Handling Enhancement

**API-Specific Error Categories:**

1. **Authentication Errors**
   - Invalid API key
   - Expired credentials
   - Rate limit exceeded

2. **Network Errors**
   - Connection timeout
   - Service unavailable
   - Network connectivity issues

3. **API Response Errors**
   - Invalid response format
   - Service errors
   - Quota exceeded

**Fallback Decision Matrix:**
```
Primary Method | Error Type        | Fallback Action
Local GPU      | CUDA Error       | Switch to API
Local GPU      | Model Load Error | Switch to API
API            | Network Error    | Switch to Local
API            | Auth Error       | Switch to Local
API            | Rate Limit       | Switch to Local (temporary)
```

## Data Models

### Enhanced AudioSegment

The existing `AudioSegment` class is enhanced with API compatibility methods:

```python
class AudioSegment:
    # Existing methods preserved
    
    def get_api_compatible_wav_bytes(self) -> bytes:
        """Get WAV bytes optimized for API transmission"""
        # Ensure format compatibility with Groq API requirements
        pass
    
    def get_size_mb(self) -> float:
        """Get audio size in MB for API limit checking"""
        pass
```

### Transcription Result Model

**Class: `TranscriptionResult`**
```python
@dataclass
class TranscriptionResult:
    text: str
    method_used: str  # "local_gpu", "groq_api"
    processing_time: float
    fallback_used: bool
    error_message: Optional[str] = None
```

### Strategy Configuration Model

**Class: `StrategyConfig`**
```python
@dataclass
class StrategyConfig:
    name: str
    enabled: bool
    priority: int
    timeout: float
    retry_count: int
    specific_config: Dict[str, Any]
```

## Error Handling

### Comprehensive Error Strategy

#### API Error Handling
1. **Connection Errors**: Implement exponential backoff with jitter
2. **Authentication Errors**: Disable API strategy and notify user
3. **Rate Limiting**: Implement intelligent backoff and temporary fallback
4. **Service Errors**: Distinguish between temporary and permanent failures

#### Fallback Coordination
1. **Failure Detection**: Monitor error patterns and success rates
2. **Strategy Health**: Track performance metrics for each strategy
3. **Recovery Detection**: Automatically return to primary strategy when healthy
4. **Circuit Breaker**: Temporarily disable failing strategies

#### Error Recovery Mechanisms
1. **Graceful Degradation**: Continue operation with available methods
2. **User Notification**: Clear status updates about method changes
3. **Data Preservation**: Ensure no audio data is lost during failures
4. **Diagnostic Logging**: Comprehensive error tracking for troubleshooting

### Error Notification Integration

The existing exception notification system is extended to handle API-specific errors:

```python
# New error categories for exception_notifier
"api_authentication": "API Authentication Error",
"api_network": "API Network Error", 
"api_rate_limit": "API Rate Limit Exceeded",
"transcription_fallback": "Transcription Fallback Activated"
```

## Testing Strategy

### Unit Testing Approach

#### Strategy Pattern Testing
- **Mock Strategies**: Test strategy switching without external dependencies
- **Fallback Logic**: Test all fallback scenarios and recovery paths
- **Configuration**: Test various configuration combinations

#### API Integration Testing
- **Mock API Responses**: Test response parsing and error handling
- **Network Simulation**: Test timeout and retry scenarios
- **Authentication**: Test credential validation and error handling

### Integration Testing

#### End-to-End Workflow Testing
- **Method Switching**: Test runtime switching during active transcription
- **Fallback Scenarios**: Test automatic fallback and recovery
- **Performance**: Compare transcription quality and speed between methods

#### Error Scenario Testing
- **Network Failures**: Simulate various network error conditions
- **API Failures**: Test API service unavailability scenarios
- **GPU Failures**: Test local transcription failures and fallback

### Performance Testing

#### Transcription Performance Metrics
- **Latency Comparison**: Local vs API transcription times
- **Accuracy Validation**: Quality comparison between methods
- **Resource Usage**: Memory and CPU usage for each method

#### Scalability Testing
- **Concurrent Requests**: Test API rate limiting behavior
- **Extended Operation**: Long-running stability testing
- **Method Switching**: Performance impact of runtime switching

### Security Testing

#### API Security Validation
- **Credential Management**: Test environment variable security
- **Data Transmission**: Validate secure API communication
- **Error Information**: Ensure no sensitive data in error messages

## Performance Considerations

### Optimization Strategies

#### API Efficiency
1. **Request Batching**: Optimize API usage within rate limits
2. **Caching**: Cache API responses for identical audio segments
3. **Compression**: Optimize audio data size for transmission

#### Local Processing Optimization
1. **Model Caching**: Maintain existing model caching strategies
2. **GPU Memory**: Optimize memory usage during method switching
3. **Resource Cleanup**: Ensure proper cleanup during strategy changes

#### Switching Performance
1. **Minimal Disruption**: Design switching to minimize processing delays
2. **Queue Management**: Handle audio queue during method transitions
3. **State Preservation**: Maintain processing state across switches

### Resource Management

#### Memory Management
- **Strategy Isolation**: Prevent memory leaks during switching
- **Model Loading**: Optimize model loading/unloading cycles
- **Audio Buffer**: Manage audio data efficiently across strategies

#### Network Resource Management
- **Connection Pooling**: Reuse API connections when possible
- **Bandwidth Optimization**: Minimize network usage
- **Timeout Management**: Balance responsiveness with reliability

## Security Considerations

### API Key Management
1. **Environment Variables**: Secure credential storage
2. **Key Validation**: Verify API key format and validity
3. **Error Handling**: Prevent key exposure in logs or error messages

### Data Privacy
1. **Audio Data**: Ensure secure transmission to API services
2. **Transcription Results**: Handle sensitive transcribed content appropriately
3. **Logging**: Sanitize logs to prevent data exposure

### Network Security
1. **HTTPS Enforcement**: Ensure encrypted API communication
2. **Certificate Validation**: Validate API service certificates
3. **Request Signing**: Implement proper API authentication