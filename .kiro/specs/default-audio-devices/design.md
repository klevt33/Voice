# Design Document

## Overview

This design refactors the audio capture system to eliminate virtual cable software dependencies by implementing direct system audio loopback capture using pyaudiowpatch. The current system requires users to configure specific microphone indices and install virtual audio cables. The new approach will automatically detect and use default system audio devices, making the application much more user-friendly and portable.

## Architecture

### Current Architecture Issues
- Requires manual configuration of `MIC_INDEX_ME` and `MIC_INDEX_OTHERS` in config.py
- Depends on virtual cable software (Voicemeeter) to redirect system audio to a virtual microphone
- Device indices can change when hardware is plugged/unplugged, breaking the configuration
- Complex setup process for end users

### New Architecture Benefits
- Automatic detection of default system microphone and speakers
- Direct system audio loopback capture without virtual cables
- Zero configuration required from users
- Resilient to hardware changes (automatically adapts to new default devices)
- Simplified deployment and setup

## Components and Interfaces

### 1. Audio Device Detection Module

**Purpose**: Automatically detect default system audio devices

**Key Functions**:
- `get_default_microphone_info()` - Returns default input device info
- `get_default_speakers_loopback_info()` - Returns default output device loopback info
- `find_loopback_device(speakers_info)` - Finds corresponding loopback device for speakers

**Implementation Approach**:
```python
def get_default_microphone_info(audio: pyaudio.PyAudio):
    """Get default system microphone device info"""
    default_input = audio.get_default_input_device_info()
    return default_input

def get_default_speakers_loopback_info(audio: pyaudio.PyAudio):
    """Get default system speakers loopback device info using pyaudiowpatch"""
    # Get default output device
    default_speakers = audio.get_device_info_by_index(
        audio.get_default_output_device_info()['index']
    )
    
    # Find corresponding loopback device
    if not default_speakers["isLoopbackDevice"]:
        for loopback in audio.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                return loopback
    
    return default_speakers
```

### 2. Modified Audio Handler

**Changes Required**:
- Remove dependency on fixed microphone indices
- Implement dynamic device detection in `recording_thread()`
- Update stream creation to use default devices
- Handle device changes gracefully

**Key Modifications**:
```python
def create_audio_stream_for_source(source: str, audio: pyaudio.PyAudio):
    """Create audio stream for ME or OTHERS source using default devices"""
    if source == "ME":
        device_info = get_default_microphone_info(audio)
    elif source == "OTHERS":
        device_info = get_default_speakers_loopback_info(audio)
    
    # Use device's native settings
    channels = int(device_info["maxInputChannels"])
    sample_rate = int(device_info["defaultSampleRate"])
    
    return audio.open(
        format=FORMAT,
        channels=channels,
        rate=sample_rate,
        input=True,
        input_device_index=device_info["index"],
        frames_per_buffer=CHUNK_SIZE
    )
```

### 3. Updated Service Manager

**Changes Required**:
- Remove `MIC_INDEX_ME` and `MIC_INDEX_OTHERS` from mic_data initialization
- Update mic_data structure to store device info instead of fixed indices
- Modify initialization to detect devices dynamically

**New Structure**:
```python
self.mic_data = {
    "ME": {"device_info": None, "stream": None},
    "OTHERS": {"device_info": None, "stream": None}
}
```

### 4. Enhanced Audio Monitor

**Changes Required**:
- Update reconnection logic to rediscover default devices
- Modify device testing to work with dynamic device detection
- Handle cases where default devices change during runtime

**Key Updates**:
- `_refresh_microphone_list()` - Now detects current default devices
- `_perform_audio_reconnection()` - Rediscovers default devices on reconnection
- Device validation logic updated for dynamic detection

### 5. Configuration Cleanup

**Changes Required**:
- Remove `MIC_INDEX_ME` and `MIC_INDEX_OTHERS` from config.py
- Update documentation to reflect automatic device detection
- Remove device index references from test files

## Data Models

### Device Information Structure
```python
@dataclass
class AudioDeviceInfo:
    index: int
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool
    source_type: str  # "ME" or "OTHERS"
```

### Updated Mic Data Structure
```python
mic_data = {
    "ME": {
        "device_info": AudioDeviceInfo,
        "stream": pyaudio.Stream,
        "recording": bool,
        "frames": List[bytes]
    },
    "OTHERS": {
        "device_info": AudioDeviceInfo,
        "stream": pyaudio.Stream,
        "recording": bool,
        "frames": List[bytes]
    }
}
```

## Error Handling

### Device Detection Failures
- **Scenario**: Default microphone not available
- **Handling**: Log error, show user-friendly message, attempt fallback to first available input device

### Loopback Device Not Found
- **Scenario**: System doesn't support loopback or no loopback device found
- **Handling**: Log detailed error, provide troubleshooting guidance, gracefully disable OTHERS audio

### Device Changes During Runtime
- **Scenario**: User changes default audio device while application is running
- **Handling**: Automatic reconnection detects new default devices and reconnects streams

### Status Bar Integration
- **Scenario**: Audio device changes, reconnection events, or errors occur
- **Handling**: Use application status bar to show real-time feedback to users

## Testing Strategy

### Unit Tests
1. **Device Detection Tests**
   - Test default microphone detection
   - Test loopback device discovery
   - Test error handling for missing devices

2. **Stream Creation Tests**
   - Test stream creation with detected devices
   - Test handling of device parameter variations
   - Test error scenarios

### Integration Tests
1. **End-to-End Audio Capture**
   - Test ME audio capture from default microphone
   - Test OTHERS audio capture from system loopback
   - Test simultaneous capture from both sources

2. **Reconnection Tests**
   - Test automatic reconnection when devices change
   - Test manual reconnection functionality
   - Test recovery from device failures

### Manual Testing Scenarios
1. **Device Change Testing**
   - Change default microphone during operation
   - Change default speakers during operation
   - Unplug/replug audio devices

2. **System Audio Testing**
   - Play various audio sources (music, videos, system sounds)
   - Test capture quality and synchronization
   - Test silence detection with system audio

## Implementation Notes

### pyaudiowpatch Integration
- pyaudiowpatch is a required dependency in requirements.txt
- The library extends pyaudio with Windows-specific loopback capabilities
- Use `get_loopback_device_info_generator()` to find loopback devices

### Status Bar User Feedback
- Leverage the application's status bar for real-time audio status updates
- Show device detection progress during startup
- Display reconnection status and success/failure messages
- Provide clear feedback when audio devices change

### Backwards Compatibility
- Remove old configuration parameters cleanly
- Provide clear migration guidance in documentation
- Ensure existing audio processing logic remains unchanged

### Performance Considerations
- Device detection should be fast and not block startup
- Cache device information to avoid repeated queries
- Minimize overhead in recording threads

### Windows-Specific Implementation
- This design is specifically for Windows using pyaudiowpatch
- Loopback audio capture is a Windows-specific feature
- Application is Windows-only, so no cross-platform considerations needed