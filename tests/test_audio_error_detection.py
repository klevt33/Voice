# tests/test_audio_error_detection.py
import unittest
import queue
import threading
import time
from unittest.mock import Mock, patch

from audio_handler import recording_thread
from audio_monitor import AudioMonitor
from exception_notifier import ExceptionNotifier

class TestAudioErrorDetection(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create fresh exception notifier instance
        ExceptionNotifier._instance = None
        self.exception_notifier = ExceptionNotifier()
        self.mock_ui_callback = Mock()
        self.exception_notifier.set_ui_update_callback(self.mock_ui_callback)
        
        # Create queues and thread control
        self.audio_queue = queue.Queue()
        self.run_threads_ref = {"active": True, "listening": True}
        
        # Mock service manager
        self.mock_service_manager = Mock()
        self.mock_service_manager.audio = Mock()
        
        # Mock mic data
        self.mic_data = {
            "ME": {"device_info": None, "stream": None},
            "OTHERS": {"device_info": None, "stream": None}
        }
    
    def tearDown(self):
        """Clean up after tests."""
        self.run_threads_ref["active"] = False
        if self.exception_notifier._cleanup_timer:
            self.exception_notifier._cleanup_timer.cancel()
    
    def test_audio_monitor_device_error_notification(self):
        """Test that AudioMonitor notifies about device errors."""
        # Create audio monitor with exception notifier
        mock_ui_controller = Mock()
        audio_monitor = AudioMonitor(self.mock_service_manager, mock_ui_controller, self.exception_notifier)
        
        # Simulate a device error
        device_error = RuntimeError("errno -9999: Unanticipated host error")
        
        # Call handle_audio_error
        audio_monitor.handle_audio_error("ME", device_error)
        
        # Verify that exception was notified
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        
        # Check UI callback was called with audio error
        self.mock_ui_callback.assert_called()
        call_args = self.mock_ui_callback.call_args[0]
        self.assertEqual(call_args[0], "audio_error")
        self.assertIn("Audio Device Error", call_args[1])
        self.assertIn("ME", call_args[1])
    
    def test_audio_monitor_non_device_error_ignored(self):
        """Test that AudioMonitor ignores non-device errors."""
        # Create audio monitor with exception notifier
        mock_ui_controller = Mock()
        audio_monitor = AudioMonitor(self.mock_service_manager, mock_ui_controller, self.exception_notifier)
        
        # Simulate a non-device error
        general_error = ValueError("Some other error")
        
        # Call handle_audio_error
        audio_monitor.handle_audio_error("ME", general_error)
        
        # Verify that exception was NOT notified (since it's not a device error)
        self.assertFalse(self.exception_notifier.is_exception_active("audio_device"))
        
        # UI callback should not have been called
        self.mock_ui_callback.assert_not_called()
    
    @patch('audio_handler.get_default_microphone_info')
    @patch('audio_handler.validate_device_info')
    def test_recording_thread_error_notification(self, mock_validate, mock_get_device):
        """Test that recording thread notifies about errors."""
        # Mock device detection to fail initially, then succeed
        mock_get_device.return_value = {"index": 0, "name": "Test Mic"}
        mock_validate.return_value = True
        
        # Mock PyAudio stream that raises an error
        mock_stream = Mock()
        mock_stream.read.side_effect = RuntimeError("Stream error")
        mock_stream.is_active.return_value = True
        
        mock_audio = Mock()
        mock_audio.open.return_value = mock_stream
        self.mock_service_manager.audio = mock_audio
        
        # Start recording thread
        thread = threading.Thread(
            target=recording_thread,
            args=("ME", self.mic_data, self.audio_queue, self.mock_service_manager, 
                  self.run_threads_ref, None, self.exception_notifier),
            daemon=True
        )
        thread.start()
        
        # Wait for thread to process and encounter error
        time.sleep(0.2)
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Verify that audio recording error was notified
        self.assertTrue(self.exception_notifier.is_exception_active("audio_recording"))
        
        # Check UI callback was called with audio error
        self.mock_ui_callback.assert_called()
        call_args = self.mock_ui_callback.call_args[0]
        self.assertEqual(call_args[0], "audio_error")
        self.assertIn("Audio Recording Error", call_args[1])
        self.assertIn("ME", call_args[1])
    
    def test_audio_error_types_mapping(self):
        """Test that different audio error types are mapped correctly."""
        test_cases = [
            ("errno -9999: Unanticipated host error", True),
            ("errno -9988: Stream closed", True),
            ("errno -9996: Invalid device", True),
            ("Device unavailable", True),
            ("Some other error", False)
        ]
        
        mock_ui_controller = Mock()
        audio_monitor = AudioMonitor(self.mock_service_manager, mock_ui_controller, self.exception_notifier)
        
        for error_message, should_be_device_error in test_cases:
            with self.subTest(error_message=error_message):
                # Reset exception notifier
                self.exception_notifier._active_exceptions.clear()
                self.mock_ui_callback.reset_mock()
                
                error = RuntimeError(error_message)
                is_device_error = audio_monitor.is_audio_device_error(error)
                
                self.assertEqual(is_device_error, should_be_device_error)
                
                # Test actual error handling
                audio_monitor.handle_audio_error("ME", error)
                
                if should_be_device_error:
                    self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
                    self.mock_ui_callback.assert_called()
                else:
                    self.assertFalse(self.exception_notifier.is_exception_active("audio_device"))
                    self.mock_ui_callback.assert_not_called()

if __name__ == '__main__':
    unittest.main()