# Design Document

## Overview

The persistent topic storage feature implements an automatic file-based backup system for captured topics. The system operates transparently in the background, creating session-based files when audio monitoring starts and closing them when monitoring stops. All captured topics are written to these files immediately upon being added to the topic list, ensuring data preservation across application crashes or unexpected shutdowns.

## Architecture

The persistent storage system integrates with the existing topic management architecture through a new `TopicStorageManager` class that acts as a middleware layer between topic capture and the UI. The storage manager listens for topic addition events and audio monitoring state changes to manage file operations automatically.

### Integration Points

1. **Topic Addition Hook**: Intercepts topics when they are added to the UI topic list
2. **Audio State Monitoring**: Responds to Listen ON/OFF events to manage file lifecycle
3. **Configuration Integration**: Reads storage path from config.py
4. **Error Handling**: Provides graceful degradation when storage operations fail

## Components and Interfaces

### TopicStorageManager Class

```python
class TopicStorageManager:
    def __init__(self, storage_folder_path: str)
    def start_session(self) -> bool
    def end_session(self) -> None
    def store_topic(self, topic: Topic) -> bool
    def _generate_filename(self) -> str
    def _ensure_storage_directory(self) -> bool
```

**Responsibilities:**
- Manage file lifecycle (create/close files based on audio state)
- Generate unique filenames with timestamp-based naming
- Write topic data to active storage file
- Handle directory creation and file I/O errors
- Maintain reference to current active file

### Storage File Format

Topics will be stored in plain text format with structured entries:

```
=== AUDIO SESSION STARTED: 2024-01-15 14:30:25 ===
[14:30] [ME] This is my first topic
[14:31] [OTHERS] This is a response from others
[14:32] [ME] Another topic from me
=== AUDIO SESSION ENDED: 2024-01-15 14:45:10 ===
```

### Filename Convention

Files will use the following naming pattern:
`topics_YYYYMMDD_HHMMSS.txt`

Examples:
- `topics_20240115_143025.txt`
- `topics_20240115_160430.txt`

If a filename collision occurs (unlikely but possible), append a counter:
- `topics_20240115_143025_001.txt`

### Configuration Integration

Add new configuration variable to config.py:

```python
# Topic storage configuration
TOPIC_STORAGE_FOLDER = r"C:\Users\[username]\Documents\AudioTopics"  # Default path
```

## Data Models

### Enhanced Topic Integration

The existing `Topic` dataclass in TopicsUI.py will be used as-is. No modifications needed since we only need to read the topic data for storage purposes.

### Storage Session State

```python
@dataclass
class StorageSession:
    file_path: str
    file_handle: Optional[TextIO]
    start_time: datetime
    topic_count: int = 0
```

## Error Handling

### File System Errors

1. **Directory Creation Failure**: Log error, disable storage for session
2. **File Creation Failure**: Log error, disable storage for session  
3. **Write Operation Failure**: Log error, continue operation (non-blocking)
4. **File Close Failure**: Log error, continue operation

### Graceful Degradation

- Storage failures do not interrupt normal application operation
- Topics continue to appear in UI even if storage fails
- Error messages logged but not displayed to user (no UI changes)
- Storage can be re-enabled on next audio session start

### Recovery Scenarios

- **Corrupted Files**: System creates new files, doesn't attempt repair
- **Permission Issues**: Logs error, suggests manual directory creation
- **Disk Full**: Logs error, continues without storage until space available

## Testing Strategy

### Unit Tests

1. **TopicStorageManager Tests**
   - File creation and naming logic
   - Directory creation handling
   - Topic formatting and writing
   - Error handling scenarios
   - Session lifecycle management

2. **Integration Tests**
   - End-to-end topic capture and storage
   - Audio state change handling
   - Configuration loading
   - File system error simulation

### Test Data

- Mock Topic objects with various sources (ME/OTHERS)
- Simulated audio session start/stop events
- File system error conditions
- Configuration variations

### Manual Testing Scenarios

1. **Normal Operation**: Start/stop audio sessions, verify files created
2. **Crash Recovery**: Force-quit application, verify topics preserved
3. **Permission Issues**: Test with read-only directories
4. **Long Sessions**: Test with many topics over extended periods
5. **Rapid Cycling**: Quick audio on/off cycles

## Implementation Notes

### Thread Safety

- Storage operations will be called from the UI thread (same thread as topic addition)
- No additional synchronization needed since UI operations are single-threaded
- File handles managed carefully to avoid resource leaks

### Performance Considerations

- File writes are synchronous but small (single topic per write)
- Files remain open during audio sessions for efficiency
- No buffering needed due to small data size and crash protection requirements

### Backward Compatibility

- No changes to existing Topic class or UI behavior
- Storage operates as pure addition to existing functionality
- Can be disabled by setting empty storage folder path