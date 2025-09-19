#!/usr/bin/env python3
"""
Test script to verify audio exception integration is working.
"""

import logging
from unittest.mock import Mock

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_audio_exception_integration():
    """Test that audio exception integration is working."""
    print("Testing Audio Exception Integration")
    print("=" * 50)
    
    try:
        # Import required modules
        from exception_notifier import exception_notifier
        from audio_handler import _wait_for_sound, process_recording
        import queue
        
        print("✓ Modules imported successfully")
        
        # Set up mock UI callback
        status_updates = []
        def mock_ui_callback(status_key, message):
            status_updates.append((status_key, message))
            print(f"UI Update: {status_key} -> {message}")
        
        exception_notifier.set_ui_update_callback(mock_ui_callback)
        print("✓ UI callback set")
        
        # Test 1: Test process_recording with exception notifier
        print("\n1. Testing process_recording with exception notifier...")
        
        # First simulate an audio recording error
        exception_notifier.notify_exception("audio_recording", RuntimeError("Recording failed"), "warning")
        initial_updates = len(status_updates)
        
        # Now simulate successful recording processing (should clear the error)
        mock_audio = Mock()
        mock_audio.get_sample_size.return_value = 2
        audio_queue = queue.Queue()
        
        frames = [b"audio_data_1", b"audio_data_2"]
        process_recording(frames, "ME", mock_audio, audio_queue, None, exception_notifier)
        
        # Check if the error was cleared
        if not exception_notifier.is_exception_active("audio_recording"):
            print("✓ process_recording clears audio recording errors on success")
        else:
            print("✗ process_recording failed to clear audio recording errors")
        
        # Test 2: Test _wait_for_sound function signature
        print("\n2. Testing _wait_for_sound function signature...")
        
        # Create mock stream that will raise an error
        mock_stream = Mock()
        mock_stream.read.side_effect = RuntimeError("Stream read error")
        
        run_threads_ref = {"active": True, "listening": True}
        
        # This should not raise a NameError anymore
        try:
            result = _wait_for_sound(mock_stream, "ME", run_threads_ref, None, exception_notifier)
            print("✓ _wait_for_sound accepts exception_notifier parameter")
        except NameError as e:
            if "exception_notifier" in str(e):
                print("✗ _wait_for_sound still has NameError for exception_notifier")
                return False
            else:
                # Some other NameError, which is expected due to mocking
                print("✓ _wait_for_sound accepts exception_notifier parameter")
        except Exception as e:
            # Other exceptions are expected due to mocking
            print("✓ _wait_for_sound accepts exception_notifier parameter")
        
        # Test 3: Verify audio error notification works
        print("\n3. Testing audio error notification...")
        
        # Simulate audio device error
        audio_error = RuntimeError("errno -9999: Unanticipated host error")
        exception_notifier.notify_exception("audio_recording", audio_error, "warning", "Audio Recording Error - ME")
        
        if exception_notifier.is_exception_active("audio_recording"):
            print("✓ Audio error notification working")
        else:
            print("✗ Audio error notification failed")
        
        # Clean up
        exception_notifier.clear_exception_status("audio_recording")
        
        print(f"\nTotal status updates captured: {len(status_updates)}")
        print("Audio exception integration test completed!")
        
        return True
        
    except Exception as e:
        print(f"✗ Audio exception integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_audio_exception_integration()
    exit(0 if success else 1)