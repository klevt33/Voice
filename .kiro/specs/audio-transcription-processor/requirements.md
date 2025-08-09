# Requirements Document

## Introduction

The Audio Transcription Processor is a real-time assistance tool designed to empower users in technical discussions by capturing, transcribing, and intelligently routing audio from dual microphone sources. The system serves as a "digital expert" that listens to conversations and provides actionable intelligence on demand through AI chat integration.

The application captures audio from two distinct sources ([ME] for the user, [OTHERS] for conversation partners), transcribes speech to text in real-time using GPU-accelerated processing, displays transcribed content in an interactive interface, and enables seamless submission to AI chat services for analysis and insights.

## Key Features

- **Real-time Audio Processing**: Continuous monitoring of multiple microphone sources with device failure resilience
- **Intelligent Transcription**: GPU-accelerated speech-to-text conversion with source identification
- **Smart Topic Routing**: Configurable auto-submission based on audio source
- **Browser Integration**: Seamless submission to AI chat interfaces with automatic connection recovery
- **Connection Resilience**: Robust reconnection capabilities for both browser and audio systems
- **User Control**: Comprehensive manual controls including unified reconnection dropdown interface

## Requirements

### Requirement 1: Dual-Source Audio Capture

**User Story:** As a user participating in technical discussions, I want the system to simultaneously capture audio from my microphone and other participants' audio sources, so that I can distinguish between my contributions and others' contributions in the transcription.

#### Acceptance Criteria

1. WHEN the system is configured with two microphone indices THEN it SHALL capture audio simultaneously from both sources without interference
2. WHEN audio is captured from each source THEN the system SHALL label transcriptions with [ME] for the user's microphone and [OTHERS] for the secondary audio source
3. WHEN audio levels exceed the configured silence threshold THEN the system SHALL begin recording from the respective source
4. WHEN silence is detected for the configured duration THEN the system SHALL stop recording and process the audio segment
5. IF a microphone device is unavailable or misconfigured THEN the system SHALL log an error and gracefully handle the failure

### Requirement 2: GPU-Accelerated Real-Time Transcription

**User Story:** As a user needing accurate and fast transcription, I want the system to leverage GPU acceleration for speech-to-text processing, so that transcriptions are generated quickly and accurately during live conversations.

#### Acceptance Criteria

1. WHEN the system initializes THEN it SHALL detect CUDA availability and use GPU acceleration if available
2. WHEN GPU is not available THEN the system SHALL fall back to CPU processing with appropriate compute type adjustments
3. WHEN audio segments are queued for transcription THEN the system SHALL process them using the faster-whisper model with configured parameters
4. WHEN transcription is complete THEN the system SHALL filter out likely hallucinations and very short segments
5. WHEN transcription fails THEN the system SHALL log the error and continue processing other audio segments
6. IF the transcription model fails to load THEN the system SHALL terminate gracefully with appropriate error messaging

### Requirement 3: Interactive Topic Management Interface

**User Story:** As a user reviewing transcribed content, I want an intuitive interface to view, select, and manage transcribed topics, so that I can efficiently organize and submit relevant content to AI services.

#### Acceptance Criteria

1. WHEN new topics are transcribed THEN the system SHALL display them in a chronological list with timestamps and source labels
2. WHEN a user clicks on a topic THEN the system SHALL toggle its selection state and display the full text
3. WHEN a user right-clicks on a topic THEN the system SHALL delete the topic from the list
4. WHEN a user clicks "Select All" or "Deselect All" THEN the system SHALL update all topic selection states accordingly
5. WHEN a user clicks "Delete Selection" or "Delete All" THEN the system SHALL remove the specified topics from the list
6. WHEN topics are successfully submitted to AI services THEN the system SHALL automatically remove them from the interface
7. IF the UI becomes unresponsive THEN the system SHALL maintain background processing and update the interface when possible

### Requirement 4: Intelligent Topic Routing

**User Story:** As a user wanting automated workflow efficiency, I want the system to automatically route transcribed topics based on configurable rules, so that relevant content is immediately sent to AI services without manual intervention.

#### Acceptance Criteria

1. WHEN auto-submit mode is set to "Off" THEN all transcribed topics SHALL be routed to the UI for manual review
2. WHEN auto-submit mode is set to "Others" THEN topics from the [OTHERS] source SHALL be automatically submitted to the browser queue
3. WHEN auto-submit mode is set to "All" THEN all transcribed topics SHALL be automatically submitted to the browser queue
4. WHEN a topic is auto-submitted THEN the system SHALL not add it to the UI topic list
5. WHEN the browser manager is unavailable THEN auto-submitted topics SHALL be logged as warnings and not processed

### Requirement 5: Browser Automation and AI Integration

**User Story:** As a user wanting seamless AI interaction, I want the system to automatically navigate and interact with AI chat websites, so that I can submit transcribed content without manual browser manipulation.

#### Acceptance Criteria

1. WHEN the system starts THEN it SHALL connect to a Chrome browser instance running with remote debugging enabled
2. WHEN connecting to an AI chat service THEN the system SHALL navigate to the configured URL and verify page readiness
3. WHEN submitting content THEN the system SHALL use the "Prime and Submit" workflow to ensure reliable message delivery
4. WHEN the submit button is disabled THEN the system SHALL prime the input field and wait for the button to become active
5. WHEN multiple submissions are queued THEN the system SHALL batch them together for efficient processing
6. WHEN submission fails due to human verification THEN the system SHALL notify the user and preserve the content
7. WHEN submission is successful THEN the system SHALL focus the browser window and update the UI status
8. IF the browser connection is lost THEN the system SHALL attempt to reconnect and log appropriate errors

### Requirement 6: Configurable AI Service Support

**User Story:** As a user working with different AI platforms, I want the system to support multiple AI chat services through configuration, so that I can switch between services without code changes.

#### Acceptance Criteria

1. WHEN the system loads configuration THEN it SHALL support multiple AI service definitions with unique selectors and settings
2. WHEN switching between AI services THEN the system SHALL load the appropriate CSS selectors and prompt files
3. WHEN prompt files are specified THEN the system SHALL load initial and message prompts from the configured file paths
4. WHEN CSS selectors are outdated THEN the system SHALL fail gracefully and provide meaningful error messages
5. IF configuration files are missing or malformed THEN the system SHALL log errors and prevent system startup

### Requirement 7: Advanced Prompting and Context Management

**User Story:** As a user requiring specialized AI interactions, I want the system to use configurable prompts and context management, so that AI responses are tailored to my specific use case and domain expertise.

#### Acceptance Criteria

1. WHEN starting a new AI thread THEN the system SHALL send the configured initial prompt to establish context
2. WHEN submitting topics THEN the system SHALL prepend the configured message prompt to provide consistent framing
3. WHEN context text is provided in the UI THEN the system SHALL include it with the [CONTEXT] prefix in submissions
4. WHEN multiple topics are submitted together THEN the system SHALL format them with appropriate source labels
5. IF prompt files cannot be loaded THEN the system SHALL log errors and continue with empty prompts

### Requirement 8: Session and State Management

**User Story:** As a user managing long conversations, I want the system to maintain session state and provide controls for starting fresh conversations, so that I can organize my AI interactions effectively.

#### Acceptance Criteria

1. WHEN the "New Thread" button is clicked THEN the system SHALL start a fresh AI conversation and optionally include context
2. WHEN the listening toggle is activated THEN the system SHALL start audio capture from both microphone sources
3. WHEN the listening toggle is deactivated THEN the system SHALL stop audio capture while preserving existing topics
4. WHEN the application shuts down THEN the system SHALL gracefully stop all threads and clean up resources
5. WHEN system state changes THEN the system SHALL update the UI status indicators appropriately

### Requirement 9: Screenshot Integration and File Handling

**User Story:** As a user sharing visual information, I want the system to automatically detect and upload new screenshots during AI interactions, so that I can provide visual context without manual file management.

#### Acceptance Criteria

1. WHEN screenshot functionality is enabled THEN the system SHALL monitor the configured screenshot folder for new images
2. WHEN new screenshots are detected THEN the system SHALL automatically upload them during the next AI submission
3. WHEN screenshots are uploaded THEN the system SHALL log the number of files processed
4. IF screenshot upload fails THEN the system SHALL log warnings but continue with text submission
5. WHEN screenshot monitoring is disabled THEN the system SHALL skip all file detection and upload processes

### Requirement 10: Error Handling and System Resilience

**User Story:** As a user depending on system reliability, I want comprehensive error handling and recovery mechanisms, so that temporary failures don't disrupt my workflow or cause data loss.

#### Acceptance Criteria

1. WHEN any component encounters an error THEN the system SHALL log detailed error information with appropriate severity levels
2. WHEN audio capture fails THEN the system SHALL continue operating other components and attempt recovery
3. WHEN transcription fails THEN the system SHALL preserve the audio data and retry processing
4. WHEN browser automation fails THEN the system SHALL preserve submission content and notify the user
5. WHEN the system detects human verification requirements THEN it SHALL preserve user input and provide clear status updates
6. WHEN threads become unresponsive THEN the system SHALL implement timeout mechanisms and graceful degradation
7. IF critical components fail during startup THEN the system SHALL prevent startup and provide diagnostic information