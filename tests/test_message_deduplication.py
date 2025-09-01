# tests/test_message_deduplication.py
import unittest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock

from exception_notifier import ExceptionNotifier

class TestMessageDeduplication(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create fresh exception notifier instance
        ExceptionNotifier._instance = None
        self.notifier = ExceptionNotifier()
        self.mock_ui_callback = Mock()
        self.notifier.set_ui_update_callback(self.mock_ui_callback)
        
        # Reduce timeouts for faster testing
        self.notifier.DEDUPLICATION_WINDOW = 1  # 1 second
        self.notifier.TIMEOUT_DURATION = 2      # 2 seconds
    
    def tearDown(self):
        """Clean up after tests."""
        if self.notifier._cleanup_timer:
            self.notifier._cleanup_timer.cancel()
    
    def test_rapid_identical_exceptions_deduplicated(self):
        """Test that rapid identical exceptions are deduplicated."""
        exception = RuntimeError("CUDA out of memory")
        
        # Send same exception multiple times rapidly
        for i in range(5):
            self.notifier.notify_exception("transcription", exception, "error", "CUDA Error")
            time.sleep(0.1)  # Small delay but within deduplication window
        
        # Should only have one active exception with count = 5
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 1)
        notification = list(active.values())[0]
        self.assertEqual(notification.count, 5)
        
        # UI should show count in the last call
        self.assertEqual(self.mock_ui_callback.call_count, 5)
        last_call_args = self.mock_ui_callback.call_args[0]
        self.assertIn("(5x)", last_call_args[1])
    
    def test_different_sources_not_deduplicated(self):
        """Test that exceptions from different sources are not deduplicated."""
        exception = RuntimeError("Device error")
        
        # Send same exception from different sources
        self.notifier.notify_exception("audio_device", exception, "warning", "Audio Error")
        self.notifier.notify_exception("audio_recording", exception, "warning", "Audio Error")
        
        # Should have two separate exceptions
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)
        
        # Each should have count = 1
        for notification in active.values():
            self.assertEqual(notification.count, 1)
    
    def test_different_messages_not_deduplicated(self):
        """Test that different messages from same source are not deduplicated."""
        exception1 = RuntimeError("CUDA out of memory")
        exception2 = RuntimeError("CUDA driver error")
        
        # Send different exceptions from same source
        self.notifier.notify_exception("transcription", exception1, "error", "CUDA Memory Error")
        self.notifier.notify_exception("transcription", exception2, "error", "CUDA Driver Error")
        
        # Should have two separate exceptions
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)
        
        # Each should have count = 1
        for notification in active.values():
            self.assertEqual(notification.count, 1)
    
    def test_deduplication_window_expiry(self):
        """Test that deduplication window expires correctly."""
        exception = RuntimeError("CUDA error")
        
        # Send first exception
        self.notifier.notify_exception("transcription", exception, "error", "CUDA Error")
        
        # Wait for deduplication window to expire
        time.sleep(1.1)
        
        # Send same exception again
        self.notifier.notify_exception("transcription", exception, "error", "CUDA Error")
        
        # Should have two separate exceptions (not deduplicated)
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)
        
        # Each should have count = 1
        for notification in active.values():
            self.assertEqual(notification.count, 1)
    
    def test_deduplication_resets_on_different_exception(self):
        """Test that deduplication count resets when a different exception occurs."""
        cuda_exception = RuntimeError("CUDA out of memory")
        audio_exception = RuntimeError("Audio device error")
        
        # Send CUDA exception multiple times
        for i in range(3):
            self.notifier.notify_exception("transcription", cuda_exception, "error", "CUDA Error")
            time.sleep(0.1)
        
        # Verify CUDA error has count = 3
        active = self.notifier.get_active_exceptions()
        cuda_notification = next(n for n in active.values() if "CUDA" in n.user_message)
        self.assertEqual(cuda_notification.count, 3)
        
        # Send different exception from same source
        self.notifier.notify_exception("transcription", audio_exception, "error", "Audio Error")
        
        # Should now have two separate exceptions
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)
        
        # Audio error should have count = 1
        audio_notification = next(n for n in active.values() if "Audio" in n.user_message)
        self.assertEqual(audio_notification.count, 1)
    
    def test_rate_limiting_prevents_ui_flooding(self):
        """Test that rapid exceptions don't flood the UI with updates."""
        exception = RuntimeError("CUDA error")
        
        # Send many exceptions very rapidly
        start_time = time.time()
        for i in range(20):
            self.notifier.notify_exception("transcription", exception, "error", "CUDA Error")
        end_time = time.time()
        
        # Should complete quickly (not blocked by UI updates)
        self.assertLess(end_time - start_time, 1.0)
        
        # Should have only one active exception with high count
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 1)
        notification = list(active.values())[0]
        self.assertEqual(notification.count, 20)
        
        # UI callback should have been called 20 times (once per exception)
        self.assertEqual(self.mock_ui_callback.call_count, 20)
        
        # Last call should show the count
        last_call_args = self.mock_ui_callback.call_args[0]
        self.assertIn("(20x)", last_call_args[1])
    
    def test_mixed_exception_types_deduplication(self):
        """Test deduplication with mixed exception types and sources."""
        cuda_error = RuntimeError("CUDA out of memory")
        audio_error = RuntimeError("Device unavailable")
        
        # Send mixed exceptions
        self.notifier.notify_exception("transcription", cuda_error, "error", "CUDA Error")
        self.notifier.notify_exception("audio_device", audio_error, "warning", "Audio Error")
        self.notifier.notify_exception("transcription", cuda_error, "error", "CUDA Error")  # Duplicate
        self.notifier.notify_exception("audio_device", audio_error, "warning", "Audio Error")  # Duplicate
        self.notifier.notify_exception("transcription", cuda_error, "error", "CUDA Error")  # Duplicate
        
        # Should have two active exceptions
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)
        
        # CUDA error should have count = 3
        cuda_notification = next(n for n in active.values() if n.source == "transcription")
        self.assertEqual(cuda_notification.count, 3)
        
        # Audio error should have count = 2
        audio_notification = next(n for n in active.values() if n.source == "audio_device")
        self.assertEqual(audio_notification.count, 2)
    
    def test_deduplication_with_custom_messages(self):
        """Test that deduplication works correctly with custom messages."""
        exception = RuntimeError("Some error")
        
        # Send same exception with same custom message
        self.notifier.notify_exception("test_source", exception, "error", "Custom Error Message")
        self.notifier.notify_exception("test_source", exception, "error", "Custom Error Message")
        self.notifier.notify_exception("test_source", exception, "error", "Custom Error Message")
        
        # Should be deduplicated
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 1)
        notification = list(active.values())[0]
        self.assertEqual(notification.count, 3)
        self.assertEqual(notification.user_message, "Custom Error Message")
        
        # Send same exception with different custom message
        self.notifier.notify_exception("test_source", exception, "error", "Different Error Message")
        
        # Should create separate exception
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)

if __name__ == '__main__':
    unittest.main()