# Exception Notification System Testing Guide

## Overview

This guide provides instructions for testing the exception notification system, including manual testing procedures and automated testing utilities.

## Environment Setup

### Enable Exception Simulation

To enable exception simulation for testing:

```bash
# Set environment variable
export ENABLE_EXCEPTION_SIMULATION=true

# Or in Windows
set ENABLE_EXCEPTION_SIMULATION=true
```

Alternatively, enable programmatically:
```python
from exception_testing_utils import enable_exception_simulation
enable_exception_simulation()
```

## Manual Testing Procedures

### 1. CUDA Error Testing

#### Simulate CUDA Out of Memory Error
```python
from exception_testing_utils import test_cuda_memory_error
test_cuda_memory_error()
```

**Expected Result**: Status bar shows red "CUDA Error - GPU out of memory"

#### Test CUDA Error Recovery
```python
from exception_notifier import exception_notifier
exception_notifier.clear_exception_status("transcription")
```

**Expected Result**: Status bar returns to normal "Status: Ready"

### 2. Audio Error Testing

#### Simulate Audio Device Error
```python
from exception_testing_utils import test_audio_device_disconnection
test_audio_device_disconnection()
```

**Expected Result**: Status bar shows orange "Audio Device Error - ME"

### 3. Exception Deduplication Testing

#### Test Rapid Repeated Exceptions
```python
from exception_testing_utils import test_exception_deduplication
test_exception_deduplication()
```

**Expected Result**: Status bar shows "Rapid Exception Test (5x)"

## Automated Testing

### Run All Tests
```bash
python -m pytest tests/ -v
```

### Run Specific Test Categories
```bash
# Core functionality tests
python -m pytest tests/test_exception_notifier.py -v

# UI integration tests  
python -m pytest tests/test_ui_exception_status.py -v

# End-to-end tests
python -m pytest tests/test_end_to_end_exception_flow.py -v
```

## Testing Utilities

### ExceptionTestingHelper

```python
from exception_testing_utils import ExceptionTestingHelper

# Check active exception count
count = ExceptionTestingHelper.get_active_exception_count()

# Print all active exceptions
ExceptionTestingHelper.print_active_exceptions()

# Wait for specific conditions
success = ExceptionTestingHelper.wait_for_exception_count(0, timeout=5.0)
```##
# ExceptionSimulator

```python
from exception_testing_utils import exception_simulator

# Simulate different CUDA errors
exception_simulator.simulate_cuda_error("memory")
exception_simulator.simulate_cuda_error("driver") 
exception_simulator.simulate_cuda_error("device")

# Simulate audio errors
exception_simulator.simulate_audio_device_error("ME", "device_unavailable")
exception_simulator.simulate_audio_recording_error("OTHERS")

# Simulate transcription errors
exception_simulator.simulate_transcription_error("generic")

# Clear all simulated exceptions
exception_simulator.clear_all_simulated_exceptions()
```

## Debug Logging

Enable debug logging for detailed exception notification information:

```python
import logging
logging.getLogger('exception_notifier').setLevel(logging.DEBUG)
```

## Common Test Scenarios

### Scenario 1: CUDA Error During Transcription
1. Start application
2. Enable listening mode
3. Simulate CUDA error: `test_cuda_memory_error()`
4. Verify red status bar with CUDA error message
5. Simulate recovery: Clear transcription exceptions
6. Verify status returns to normal

### Scenario 2: Audio Device Disconnection
1. Start application with audio devices connected
2. Simulate device error: `test_audio_device_disconnection()`
3. Verify orange status bar with audio error message
4. Simulate reconnection: Clear audio exceptions
5. Verify status returns to normal

### Scenario 3: Multiple Simultaneous Errors
1. Simulate CUDA error
2. Simulate audio error
3. Verify both errors are tracked
4. Clear one error type
5. Verify remaining error is still shown
6. Clear remaining error
7. Verify status returns to normal

## Troubleshooting

### Exception Simulation Not Working
- Verify `ENABLE_EXCEPTION_SIMULATION=true` is set
- Check that `exception_simulator.simulation_enabled` returns `True`
- Ensure exception_notifier is properly initialized

### Status Updates Not Appearing
- Verify UI callback is set: `exception_notifier._ui_update_callback` should not be None
- Check that Tkinter main loop is running for UI updates
- Verify no exceptions in UI update callback

### Tests Failing
- Ensure clean test environment (reset ExceptionNotifier singleton)
- Check for proper mock setup in integration tests
- Verify timing issues with async operations

## Performance Testing

### Load Testing
```python
# Test with many rapid exceptions
for i in range(100):
    exception_simulator.simulate_cuda_error("memory")
```

### Memory Testing
```python
# Test cleanup and memory usage
import gc
exception_simulator.simulate_rapid_exceptions(1000, 0.001)
gc.collect()
# Monitor memory usage
```

## Integration with CI/CD

Add to your CI pipeline:
```yaml
- name: Run Exception Notification Tests
  run: |
    export ENABLE_EXCEPTION_SIMULATION=true
    python -m pytest tests/test_exception_notifier.py -v
    python -m pytest tests/test_end_to_end_exception_flow.py -v
```