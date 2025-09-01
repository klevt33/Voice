# tests/test_exception_notifier.py
import unittest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from exception_notifier import ExceptionNotifier, ExceptionSeverity, ExceptionNotification

class TestExceptionNotifier(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a fresh instance for each test
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
    
    def test_singleton_pattern(self):
        """Test that ExceptionNotifier follows singleton pattern."""
        notifier1 = ExceptionNotifier()
        notifier2 = ExceptionNotifier()
        self.assertIs(notifier1, notifier2)
    
    def test_basic_exception_notification(self):
        """Test basic exception notification functionality."""
        exception = ValueError("Test error")
        
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        
        # Check that UI callback was called
        self.mock_ui_callback.assert_called_once()
        args = self.mock_ui_callback.call_args[0]
        self.assertEqual(args[1], "Test message")
        
        # Check that exception is active
        self.assertTrue(self.notifier.is_exception_active("test_source"))
    
    def test_cuda_error_detection(self):
        """Test CUDA error detection and message generation."""
        cuda_exception = RuntimeError("CUDA out of memory")
        
        self.notifier.notify_exception("transcription", cuda_exception, "error")
        
        # Check that CUDA error status was used
        self.mock_ui_callback.assert_called_once()
        args = self.mock_ui_callback.call_args[0]
        self.assertEqual(args[0], "cuda_error")
        self.assertIn("CUDA Error", args[1])
    
    def test_audio_error_detection(self):
        """Test audio error detection and message generation."""
        audio_exception = RuntimeError("Device unavailable")
        
        self.notifier.notify_exception("audio_recording", audio_exception, "warning")
        
        # Check that audio error status was used
        self.mock_ui_callback.assert_called_once()
        args = self.mock_ui_callback.call_args[0]
        self.assertEqual(args[0], "audio_error")
        self.assertIn("Audio", args[1])
    
    def test_message_deduplication(self):
        """Test that identical exceptions are deduplicated."""
        exception = ValueError("Test error")
        
        # Send same exception twice quickly
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        
        # Should only have one active exception with count = 2
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 1)
        notification = list(active.values())[0]
        self.assertEqual(notification.count, 2)
        
        # UI should show count
        self.assertEqual(self.mock_ui_callback.call_count, 2)
        last_call_args = self.mock_ui_callback.call_args[0]
        self.assertIn("(2x)", last_call_args[1])
    
    def test_deduplication_window_expiry(self):
        """Test that deduplication window expires correctly."""
        exception = ValueError("Test error")
        
        # Send first exception
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        
        # Wait for deduplication window to expire
        time.sleep(1.1)
        
        # Send same exception again
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        
        # Should have two separate exceptions
        active = self.notifier.get_active_exceptions()
        self.assertEqual(len(active), 2)
    
    def test_clear_exception_status(self):
        """Test clearing exception status for recovery."""
        exception = ValueError("Test error")
        
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        self.assertTrue(self.notifier.is_exception_active("test_source"))
        
        # Clear the exception
        self.notifier.clear_exception_status("test_source")
        
        # Should no longer be active
        self.assertFalse(self.notifier.is_exception_active("test_source"))
        
        # UI should be updated to success status
        self.mock_ui_callback.assert_called_with("success", "Status: Ready")
    
    def test_multiple_sources(self):
        """Test handling exceptions from multiple sources."""
        exception1 = ValueError("Error 1")
        exception2 = RuntimeError("Error 2")
        
        self.notifier.notify_exception("source1", exception1, "error", "Message 1")
        self.notifier.notify_exception("source2", exception2, "warning", "Message 2")
        
        # Both should be active
        self.assertTrue(self.notifier.is_exception_active("source1"))
        self.assertTrue(self.notifier.is_exception_active("source2"))
        
        # Clear one source
        self.notifier.clear_exception_status("source1")
        
        # Only source2 should be active
        self.assertFalse(self.notifier.is_exception_active("source1"))
        self.assertTrue(self.notifier.is_exception_active("source2"))
    
    def test_severity_handling(self):
        """Test different severity levels."""
        exception = ValueError("Test error")
        
        # Test each severity level
        severities = ["error", "warning", "info"]
        for severity in severities:
            with self.subTest(severity=severity):
                self.notifier.notify_exception(f"test_{severity}", exception, severity)
                
                # Check that notification was created with correct severity
                active = self.notifier.get_active_exceptions()
                notification = next(n for n in active.values() if n.source == f"test_{severity}")
                self.assertEqual(notification.severity.value, severity)
    
    def test_invalid_severity_fallback(self):
        """Test fallback behavior for invalid severity."""
        exception = ValueError("Test error")
        
        self.notifier.notify_exception("test_source", exception, "invalid_severity")
        
        # Should fallback to ERROR severity
        active = self.notifier.get_active_exceptions()
        notification = list(active.values())[0]
        self.assertEqual(notification.severity, ExceptionSeverity.ERROR)
    
    def test_exception_history(self):
        """Test that exception history is maintained."""
        exception = ValueError("Test error")
        
        # Generate multiple exceptions
        for i in range(5):
            self.notifier.notify_exception("test_source", exception, "error", f"Message {i}")
            time.sleep(0.1)  # Small delay to ensure different timestamps
        
        # Check that history is maintained (implementation detail, but useful for debugging)
        self.assertTrue(len(self.notifier._exception_history) > 0)
    
    def test_ui_callback_error_handling(self):
        """Test that UI callback errors don't break the notifier."""
        # Set up a callback that raises an exception
        error_callback = Mock(side_effect=Exception("UI callback error"))
        self.notifier.set_ui_update_callback(error_callback)
        
        exception = ValueError("Test error")
        
        # This should not raise an exception
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        
        # Exception should still be tracked
        self.assertTrue(self.notifier.is_exception_active("test_source"))
    
    def test_timeout_cleanup(self):
        """Test that old exceptions are cleaned up after timeout."""
        exception = ValueError("Test error")
        
        self.notifier.notify_exception("test_source", exception, "error", "Test message")
        self.assertTrue(self.notifier.is_exception_active("test_source"))
        
        # Wait for timeout
        time.sleep(2.1)
        
        # Trigger cleanup manually for testing
        self.notifier._cleanup_old_exceptions()
        
        # Exception should be cleaned up
        self.assertFalse(self.notifier.is_exception_active("test_source"))

if __name__ == '__main__':
    unittest.main()