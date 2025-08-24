# Requirements Document

## Introduction

This feature refactors the audio capture system to eliminate the dependency on virtual cable software by implementing direct system audio loopback capture. The current implementation requires users to install and configure virtual audio cables to redirect system audio to a virtual microphone. The new approach will use the default system microphone for [ME] audio and capture system output audio directly using loopback functionality for [OTHERS] audio, making the application much easier to set up and use.

## Requirements

### Requirement 1

**User Story:** As a user, I want the application to automatically use my default microphone without requiring manual configuration, so that I don't need to determine and configure microphone indexes.

#### Acceptance Criteria

1. WHEN the application starts THEN the system SHALL automatically detect and use the default system microphone for [ME] audio capture
2. WHEN the default microphone changes THEN the system SHALL automatically reconnect to the new default microphone
3. WHEN microphone reconnection occurs THEN the system SHALL maintain audio capture functionality without user intervention

### Requirement 2

**User Story:** As a user, I want the application to capture system output audio directly without requiring virtual cable software, so that I can use the application without additional software dependencies.

#### Acceptance Criteria

1. WHEN the application starts THEN the system SHALL automatically detect and use the default system output device for [OTHERS] audio capture via loopback
2. WHEN system audio plays through the default output device THEN the system SHALL capture that audio using pyaudiowpatch loopback functionality
3. WHEN the default output device changes THEN the system SHALL automatically reconnect to the new default output device loopback
4. WHEN no system audio is playing THEN the system SHALL continue monitoring without errors

### Requirement 3

**User Story:** As a user, I want the application configuration to be simplified by removing manual audio device configuration, so that setup is automatic and maintenance-free.

#### Acceptance Criteria

1. WHEN the application is configured THEN the system SHALL NOT require MIC_INDEX_OTHERS and MIC_INDEX_ME parameters in config.py
2. WHEN the application starts THEN the system SHALL automatically determine audio device settings without user configuration
3. WHEN audio devices change THEN the system SHALL adapt automatically without requiring configuration updates

### Requirement 4

**User Story:** As a developer, I want the audio reconnection functionality to work with default audio devices, so that the existing reconnection features continue to function properly.

#### Acceptance Criteria

1. WHEN manual audio reconnection is triggered THEN the system SHALL reconnect to current default microphone and output device
2. WHEN automatic audio reconnection occurs THEN the system SHALL reconnect to current default microphone and output device
3. WHEN reconnection fails THEN the system SHALL retry with appropriate error handling
4. WHEN reconnection succeeds THEN the system SHALL resume normal audio capture operation

### Requirement 5

**User Story:** As a developer, I want to ensure all application components work correctly with the new audio architecture, so that no functionality is broken by this change.

#### Acceptance Criteria

1. WHEN audio monitoring components access audio streams THEN the system SHALL provide the same interface as before
2. WHEN audio transcription processes audio data THEN the system SHALL receive audio data in the expected format
3. WHEN UI components display audio status THEN the system SHALL show accurate status for both audio streams
4. WHEN connection monitoring checks audio health THEN the system SHALL report correct connection status for both streams