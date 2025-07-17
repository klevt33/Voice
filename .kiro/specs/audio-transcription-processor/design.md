# Design Document

## Overview

The Audio Transcription Processor employs a modular, multi-threaded architecture designed for real-time audio processing, transcription, and AI integration. The system uses a centralized orchestrator pattern with clear separation of concerns, enabling responsive user interaction while maintaining robust background processing.

The architecture prioritizes thread safety, resource management, and graceful error handling to ensure reliable operation during extended use. Communication between components occurs through thread-safe queues, allowing for asynchronous processing and preventing UI blocking.

## Architecture

### High-Level Architecture

The system follows a layered architecture with the following primary layers:

1. **Presentation Layer** - Tkinter-based UI with MVC pattern separation
2. **Application Layer** - Core orchestration and business logic
3. **Service Layer** - Audio processing, transcription, and browser automation services
4. **Integration Layer** - External system interfaces (AI chat services, audio devices)

### Threading Model

The application uses a multi-threaded design to ensure responsiveness:

- **Main Thread**: Tkinter UI event loop (single-threaded requirement)
- **Audio Recording Threads**: Two dedicated threads for dual-source audio capture
- **Transcription Thread**: Single thread for speech-to-text processing
- **Topic Processing Thread**: Routes transcribed content based on configuration
- **Browser Communication Thread**: Handles AI service interactions
- **UI Topic Queue Thread**: Updates UI with new transcribed content

### Communication Architecture

Inter-thread communication uses thread-safe queues:

```
Audio Sources → audio_queue → Transcription → transcribed_topics_queue → Topic Router
                                                                              ↓
UI Topic Queue ← Topic Router → Browser Queue → AI Chat Services
```

## Components and Interfaces

### Core Orchestrator (`AudioToChat`)

**Responsibilities:**
- Application lifecycle management
- Component initialization and coordination
- Signal handling and graceful shutdown
- Topic processing coordination

**Key Interfaces:**
- `run()`: Main application entry point
- `shutdown()`: Coordinated system shutdown
- `topic_processing_loop()`: Central topic routing logic
- UI callback methods for user interactions

### State Management (`StateManager`)

**Responsibilities:**
- Centralized application state storage
- Thread-safe state access
- Configuration state management

**Key State:**
- `run_threads_ref`: Thread lifecycle control
- `auto_submit_mode`: Topic routing configuration
- Listening state management

### Service Management (`ServiceManager`)

**Responsibilities:**
- External service lifecycle management
- Audio system initialization
- Browser automation setup
- Thread management for services

**Key Services:**
- PyAudio initialization and management
- BrowserManager lifecycle
- Audio recording thread coordination
- Transcription service management

### UI Layer

#### UIController (`TopicsUI`)
**Responsibilities:**
- UI business logic and event handling
- Topic list management
- User interaction processing
- Status updates and notifications

**Key Methods:**
- Topic selection and management
- Submission coordination
- Auto-submit mode handling
- Browser status updates

#### UIView (`ui_view`)
**Responsibilities:**
- Widget creation and layout
- Visual presentation logic
- Event binding setup
- Status indicator management

**Key Components:**
- Topic listbox with multi-selection
- Context text input area
- Control buttons and toggles
- Status bar with color-coded indicators

### Audio Processing Layer

#### Audio Handler (`audio_handler`)
**Responsibilities:**
- Dual-source audio capture
- Voice activity detection
- Audio segment processing
- Stream management

**Key Features:**
- Configurable silence detection
- Automatic recording start/stop based on silence duration
- Maximum audio fragment duration limiting (configurable, default 120 seconds)
- Automatic fragment completion and continuation for long recordings
- Audio level monitoring
- WAV format conversion

#### Transcription Engine (`transcription`)
**Responsibilities:**
- Speech-to-text conversion
- GPU/CPU optimization
- Model caching and management
- Quality filtering

**Key Features:**
- faster-whisper integration
- CUDA acceleration support
- Hallucination filtering
- Performance monitoring

### Browser Automation Layer

#### BrowserManager (`browser`)
**Responsibilities:**
- High-level browser coordination
- Submission queue management
- Screenshot handling
- Window focus management

**Key Features:**
- Prime and Submit workflow
- Batch processing optimization
- Screenshot auto-upload
- Connection management

#### ChatPage (`chat_page`)
**Responsibilities:**
- Low-level Selenium interactions
- Site-specific element handling
- Input field management
- Submission verification

**Key Features:**
- CSS selector-based element location
- Clipboard-based text input
- Human verification detection
- Error state handling

### Topic Routing (`TopicRouter`)

**Responsibilities:**
- Intelligent content routing
- Auto-submit logic implementation
- Queue management coordination

**Routing Logic:**
- Manual mode: All topics → UI
- Others mode: [OTHERS] topics → Browser, [ME] topics → UI
- All mode: All topics → Browser

## Data Models

### Topic Model
```python
@dataclass
class Topic:
    text: str              # Transcribed content
    timestamp: datetime    # Creation timestamp
    source: str           # "ME" or "OTHERS"
    selected: bool        # UI selection state
```

### AudioSegment Model
```python
class AudioSegment:
    frames: List[bytes]    # Raw audio data
    sample_rate: int       # Audio sample rate
    channels: int          # Audio channel count
    sample_width: int      # Sample bit width
    timestamp: str         # Creation timestamp
    source: str           # Source identifier
```

### Configuration Model
The system uses a centralized configuration approach with the following key areas:

- **Audio Configuration**: Sample rates, chunk sizes, silence thresholds
- **Transcription Configuration**: Model selection, compute types, language settings
- **Browser Configuration**: Debug addresses, screenshot settings
- **AI Service Configuration**: URLs, selectors, prompt file paths

## Error Handling

### Error Categories and Strategies

#### Audio System Errors
- **Device Unavailable**: Log error, continue with available devices
- **Stream Interruption**: Attempt reconnection, preserve existing data
- **Configuration Errors**: Fail fast with diagnostic information

#### Transcription Errors
- **Model Loading Failure**: Terminate gracefully with clear messaging
- **Processing Errors**: Retry with exponential backoff, preserve audio data
- **GPU Unavailability**: Automatic fallback to CPU processing

#### Browser Automation Errors
- **Connection Failure**: Preserve submission content, notify user
- **Element Not Found**: Log detailed selector information, attempt recovery
- **Human Verification**: Preserve input, provide clear status updates
- **Timeout Errors**: Implement progressive timeout strategies

#### UI Errors
- **Widget Errors**: Graceful degradation, maintain core functionality
- **Update Failures**: Queue updates for retry, prevent UI freezing

### Error Recovery Mechanisms

1. **Graceful Degradation**: Continue operation with reduced functionality
2. **Automatic Retry**: Exponential backoff for transient failures
3. **State Preservation**: Maintain user data during error conditions
4. **User Notification**: Clear, actionable error messages
5. **Diagnostic Logging**: Comprehensive error tracking for troubleshooting

## Testing Strategy

### Unit Testing Approach

#### Component-Level Testing
- **Audio Processing**: Mock PyAudio streams, test silence detection
- **Transcription**: Mock faster-whisper, test filtering logic
- **UI Components**: Test event handling and state management
- **Browser Automation**: Mock Selenium interactions, test element handling

#### Integration Testing
- **Queue Communication**: Test inter-thread message passing
- **Service Coordination**: Test component lifecycle management
- **Error Propagation**: Test error handling across component boundaries

### System Testing Approach

#### End-to-End Scenarios
- **Complete Workflow**: Audio capture → Transcription → AI submission
- **Error Recovery**: Component failure and recovery scenarios
- **Performance Testing**: Extended operation under load
- **Configuration Testing**: Multiple AI service configurations

#### User Acceptance Testing
- **Workflow Validation**: Real-world usage scenarios
- **UI Responsiveness**: User interaction testing
- **Error Handling**: User-facing error scenarios

### Test Data Management
- **Audio Samples**: Curated test audio for various scenarios
- **Mock Responses**: Simulated AI service responses
- **Configuration Sets**: Multiple valid and invalid configurations
- **Error Conditions**: Systematic error injection testing

### Performance Testing
- **Memory Usage**: Long-running operation monitoring
- **CPU Utilization**: Multi-threading efficiency testing
- **GPU Utilization**: CUDA acceleration verification
- **Response Times**: Real-time processing requirements

### Security Testing
- **Input Validation**: Malformed audio and text input handling
- **File System Access**: Screenshot folder permission testing
- **Browser Security**: Selenium interaction security validation
- **Configuration Security**: Sensitive data handling verification