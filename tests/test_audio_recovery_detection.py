# tests/test_audio_recovery_detection.py
import unittest
import queue
import threading
import time
from unittest.mock import Mock, patch

from audio_handler import process_recording
from audio_monitor import AudioMonitor
from exception_notifier import ExceptionNotifier

class TestAudioRecoveryDetection(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create fresh exception notifier instance
        ExceptionNotifier._instance = None
        self.exception_notifier = ExceptionNotifier()
        self.mock_ui_callback = Mock()
        self.exception_notifier.set_ui_update_callback(self.mock_ui_callback)
        
        # Mock service manager
        self.mock_service_manager = Mock()
        self.mock_service_manager.audio = Mock()
        self.mock_service_manager.mic_data = {
            "ME": {"device_info": {"name": "Test Microphone"}},
            "OTHERS": {"device_info": {"name": "Test Speakers"}}
        }
    
    def tearDown(self):
        """Clean up after tests."""
        if self.exception_notifier._cleanup_timer:
            self.exception_notifier._cleanup_timer.cancel()
    
    def test_audio_reconnection_recovery(self):
        """Test that audio errors are cleared on successful reconnection."""
        # Create audio monitor with exception notifier
        mock_ui_controller = Mock()
        audio_monitor = AudioMonitor(self.mock_service_manager, mock_ui_controller, self.exception_notifier)
        
        # Simulate audio device and recording errors
        device_error = RuntimeError("errno -9999: Unanticipated host error")
        recording_error = RuntimeError("Stream error")
        
        self.exception_notifier.notify_exception("audio_device", device_error, "warning")
        self.exception_notifier.notify_exception("audio_recording", recording_error, "warning")
        
        # Verify both errors are active
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        self.assertTrue(self.exception_notifier.is_exception_active("audio_recording"))
        
        # Mock successful reconnection
        with patch.object(audio_monitor, '_perform_combined_audio_reconnection', return_value=True):
            success = audio_monitor.reconnect_all_audio_sources()
        
        self.assertTrue(success)
        
        # Verify that both audio errors were cleared
        self.assertFalse(self.exception_notifier.is_exception_active("audio_device"))
        self.assertFalse(self.exception_notifier.is_exception_active("audio_recording"))
    
    def test_audio_recording_recovery(self):
        """Test that audio recording errors are cleared on successful recording."""
        # Simulate an audio recording error
        recording_error = RuntimeError("Recording failed")
        self.exception_notifier.notify_exception("audio_recording", recording_error, "warning")
        
        # Verify error is active
        self.assertTrue(self.exception_notifier.is_exception_active("audio_recording"))
        
        # Simulate successful recording processing
        mock_audio = Mock()
        mock_audio.get_sample_size.return_value = 2
        audio_queue = queue.Queue()
        
        frames = [b"audio_data_1", b"audio_data_2"]
        process_recording(frames, "ME", mock_audio, audio_queue, None, self.exception_notifier)
        
        # Verify that audio recording error was cleared
        self.assertFalse(self.exception_notifier.is_exception_active("audio_recording"))
        
        # Verify that audio segment was queued
        self.assertFalse(audio_queue.empty())
    
    def test_partial_recovery_with_multiple_errors(self):
        """Test recovery when only some audio errors are resolved."""
        # Create audio monitor with exception notifier
        mock_ui_controller = Mock()
        audio_monitor = AudioMonitor(self.mock_service_manager, mock_ui_controller, self.exception_notifier)
        
        # Simulate multiple types of errors
        device_error = RuntimeError("errno -9999: Unanticipated host error")
        transcription_error = RuntimeError("CUDA out of memory")
        
        self.exception_notifier.notify_exception("audio_device", device_error, "warning")
        self.exception_notifier.notify_exception("transcription", transcription_error, "error")
        
        # Verify both errors are active
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        self.assertTrue(self.exception_notifier.is_exception_active("transcription"))
        
        # Reset mock to track recovery
        self.mock_ui_callback.reset_mock()
        
        # Mock successful audio reconnection (should only clear audio errors)
        with patch.object(audio_monitor, '_perform_combined_audio_reconnection', return_value=True):
            success = audio_monitor.reconnect_all_audio_sources()
        
        self.assertTrue(success)
        
        # Verify that only audio error was cleared, transcription error remains
        self.assertFalse(self.exception_notifier.is_exception_active("audio_device"))
        self.assertTrue(self.exception_notifier.is_exception_active("transcription"))
        
        # Should still show the remaining transcription error, not "Ready"
        # The UI update should show the remaining exception
        latest_call = self.mock_ui_callback.call_args
        if latest_call:
            # Should show the transcription error that's still active
            self.assertIn("CUDA", latest_call[0][1])
    
    def test_failed_reconnection_preserves_errors(self):
        """Test that failed reconnection doesn't clear errors."""
        # Create audio monitor with exception notifier
        mock_ui_controller = Mock()
        audio_monitor = AudioMonitor(self.mock_service_manager, mock_ui_controller, self.exception_notifier)
        
        # Simulate audio device error
        device_error = RuntimeError("errno -9999: Unanticipated host error")
        self.exception_notifier.notify_exception("audio_device", device_error, "warning")
        
        # Verify error is active
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        
        # Mock failed reconnection
        with patch.object(audio_monitor, '_perform_combined_audio_reconnection', return_value=False):
            success = audio_monitor.reconnect_all_audio_sources()
        
        self.assertFalse(success)
        
        # Verify that audio error is still active (not cleared on failed reconnection)
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
    
    def test_recording_recovery_with_device_error_active(self):
        """Test that recording recovery only clears recording errors, not device errors."""
        # Simulate both device and recording errors
        device_error = RuntimeError("errno -9999: Unanticipated host error")
        recording_error = RuntimeError("Recording failed")
        
        self.exception_notifier.notify_exception("audio_device", device_error, "warning")
        self.exception_notifier.notify_exception("audio_recording", recording_error, "warning")
        
        # Verify both errors are active
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        self.assertTrue(self.exception_notifier.is_exception_active("audio_recording"))
        
        # Simulate successful recording processing
        mock_audio = Mock()
        mock_audio.get_sample_size.return_value = 2
        audio_queue = queue.Queue()
        
        frames = [b"audio_data_1", b"audio_data_2"]
        process_recording(frames, "ME", mock_audio, audio_queue, None, self.exception_notifier)
        
        # Verify that only recording error was cleared, device error remains
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        self.assertFalse(self.exception_notifier.is_exception_active("audio_recording"))

if __name__ == '__main__':
    unittest.main()