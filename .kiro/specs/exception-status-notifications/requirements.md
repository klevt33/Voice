# Requirements Document

## Introduction

This feature implements a mechanism to notify users about unexpected exceptions through status line messages in the UI. The primary goal is to surface critical errors (especially CUDA-related issues) that currently only appear in logs, making them visible to users without requiring them to check log windows. This addresses the specific problem where CUDA failures cause transcription to silently fail while the application appears to be functioning normally.

## Requirements

### Requirement 1

**User Story:** As a user, I want to be notified when CUDA-related errors occur during transcription, so that I understand why transcriptions are not appearing.

#### Acceptance Criteria

1. WHEN a CUDA-related exception occurs in the transcription thread THEN the system SHALL display an error status message in the UI status bar
2. WHEN a CUDA error is detected THEN the status message SHALL include "CUDA Error" and a brief description of the issue
3. WHEN a CUDA error status is displayed THEN the status indicator SHALL show red color to indicate an error state
4. WHEN the CUDA error is resolved (successful transcription occurs) THEN the status SHALL automatically return to normal state

### Requirement 2

**User Story:** As a user, I want to see status notifications for other critical exceptions that affect core functionality, so that I can understand when the application is not working properly.

#### Acceptance Criteria

1. WHEN an exception occurs in audio recording threads THEN the system SHALL display a warning status message indicating audio issues
2. WHEN an exception occurs in the transcription thread (non-CUDA) THEN the system SHALL display an error status message
3. WHEN multiple exceptions occur rapidly THEN the system SHALL avoid flooding the status bar with repeated messages
4. WHEN an exception status is displayed THEN it SHALL remain visible for at least 10 seconds before being replaced by normal status

### Requirement 3

**User Story:** As a developer, I want a centralized exception notification system, so that I can easily add status notifications for new error conditions without modifying UI code directly.

#### Acceptance Criteria

1. WHEN implementing exception notifications THEN the system SHALL provide a centralized mechanism for reporting exceptions to the status bar
2. WHEN an exception is reported THEN the system SHALL support different severity levels (error, warning, info)
3. WHEN an exception notification is sent THEN it SHALL include the source component and a user-friendly message
4. WHEN the notification system is implemented THEN it SHALL not require major architectural changes to existing components

### Requirement 4

**User Story:** As a user, I want exception notifications to be non-intrusive, so that they inform me of issues without disrupting my workflow.

#### Acceptance Criteria

1. WHEN an exception notification is displayed THEN it SHALL only appear in the existing status bar area
2. WHEN an exception occurs THEN the system SHALL NOT display popup dialogs or modal windows
3. WHEN an exception notification is shown THEN normal application functionality SHALL remain available
4. WHEN multiple exceptions of the same type occur THEN the system SHALL consolidate them into a single status message with a count if appropriate