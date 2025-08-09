# Requirements Document

## Introduction

This feature implements persistent storage for captured topics to ensure data preservation across application crashes, computer restarts, or other unexpected shutdowns. The system will automatically save all captured topics to files without requiring any user interface changes, providing a reliable backup mechanism that operates transparently in the background.

## Requirements

### Requirement 1

**User Story:** As a user, I want all captured topics to be automatically saved to files, so that I don't lose my topics if the application or computer crashes.

#### Acceptance Criteria

1. WHEN a topic is captured and added to the topic list THEN the system SHALL write the topic to the current active storage file
2. WHEN the audio monitoring is enabled (Listen=ON) THEN the system SHALL create a new storage file with a unique filename
3. WHEN the audio monitoring is disabled (Listen=OFF) THEN the system SHALL close the current storage file
4. WHEN a new storage file is created THEN the filename SHALL include a timestamp to ensure uniqueness
5. IF the application crashes or restarts THEN previously saved topics SHALL remain intact in their respective files

### Requirement 2

**User Story:** As a user, I want the topic storage to be independent of UI interactions, so that my saved topics remain complete regardless of what I do with topics in the interface.

#### Acceptance Criteria

1. WHEN a user submits a topic THEN the topic SHALL remain in the storage file unchanged
2. WHEN a user deletes a topic from the UI THEN the topic SHALL remain in the storage file unchanged
3. WHEN a user copies a topic THEN the topic SHALL remain in the storage file unchanged
4. WHEN a topic is captured THEN it SHALL be saved to the file before any UI interactions can affect it

### Requirement 3

**User Story:** As a user, I want to configure where topic files are stored, so that I can organize them according to my preferences and system setup.

#### Acceptance Criteria

1. WHEN the system needs to determine the storage location THEN it SHALL read the folder path from config.py
2. WHEN the configured folder path does not exist THEN the system SHALL create the directory structure
3. WHEN the config.py file specifies a storage path THEN all topic files SHALL be created in that location
4. IF no storage path is configured THEN the system SHALL use a default location within the application directory

### Requirement 4

**User Story:** As a user, I want each audio session to have its own topic file, so that I can easily identify and manage topics from different sessions.

#### Acceptance Criteria

1. WHEN audio monitoring starts (Listen=ON) THEN the system SHALL create a new file with a unique name
2. WHEN audio monitoring stops (Listen=OFF) THEN the system SHALL close the current file
3. WHEN a new file is created THEN the filename SHALL include date and time information for uniqueness
4. WHEN multiple audio sessions occur THEN each session SHALL have its own separate file
5. IF the system needs to create a file with a name that already exists THEN it SHALL append additional identifiers to ensure uniqueness

### Requirement 5

**User Story:** As a user, I want to manually manage the storage files, so that I can delete old files or organize them as needed without the application interfering.

#### Acceptance Criteria

1. WHEN a user manually deletes a storage file THEN the system SHALL continue operating normally
2. WHEN the system writes to storage files THEN it SHALL not automatically delete or modify existing files
3. WHEN storage files exist in the configured directory THEN the system SHALL not interfere with user file management operations
4. IF a user moves or renames storage files THEN the system SHALL not attempt to track or update those changes