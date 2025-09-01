# tests/test_timeout_cleanup.py
import unittest
import time
import threading
from unittest.mock import Mock

from exception_notifier import ExceptionNotifier

class TestTimeoutCleanup(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create fresh exception notifier instance
        ExceptionNotifier._instance = None
        self.notifier = ExceptionNotifier()
        self.mock_ui_callback = Mock()
        self.notifier.set_ui_update_callback(self.mock_ui_callback)
        
        # Reduce timeout for faster testing
        self.notifier.TIMEOUT_DURATION = 1  # 1 second
    
    def tearDown(self):
        """Clean up after tests."""
        if self.notifier._cleanup_timer:
            self.notifier._cleanup_timer.cancel()
    
    def test_single_exception_timeout_cleanup(self):
        """Test that a single exception is cleaned up after timeout."""
        exception = RuntimeError("Test error")
        
        # Add exception
        self.notifier.notify_exception("test_source", exception, "error", "Test Error")
        
        # Verify exception is active
        self.assertTrue(self.notifier.is_exception_active("test_source"))
        
        # Wait for timeout
        time.sleep(1.2)
        
        # Manually trigger cleanup for testing
        self.notifier._cleanup_old_exceptions()
        
        # Exception should be cleaned up
        self.assertFalse(self.notifier.is_exception_active("test_source"))
        
        # UI should be updated to "Ready" status
        self.mock_ui_callback.assert_called()
        # Find the "Ready" call
        ready_call = None
        for call in self.mock_ui_callback.call_args_list:
            if len(call[0]) >= 2 and "Ready" in call[0][1]:
                ready_call = call
                break
        self.assertIsNotNone(ready_call)
    
    def test_multiple_exceptions_partial_timeout(self):
        """Test cleanup when only some exceptions timeout."""
        exception1 = RuntimeError("Error 1")
        exception2 = RuntimeError("Error 2")
        
        # Add first exception
        self.notifier.notify_exception("source1", exception1, "error", "Error 1")
        
        # Wait a bit
        time.sleep(0.6)
        
        # Add second exception (newer)
        self.notifier.notify_exception("source2", exception2, "warning", "Error 2")
        
        # Wait for first exception to timeout but not second
        time.sleep(0.6)
        
        # Manually trigger cleanup
        self.notifier._cleanup_old_exceptions()
        
        # First exception should be cleaned up, second should remain
        self.assertFalse(self.notifier.is_exception_active("source1"))
        self.assertTrue(self.notifier.is_exception_active("source2"))
        
        # UI should show the remaining exception, not "Ready"
        latest_call = self.mock_ui_callback.call_args
        if latest_call:
            self.assertIn("Error 2", latest_call[0][1])
    
    def test_no_cleanup_for_recent_exceptions(self):
        """Test that recent exceptions are not cleaned up."""
        exception = RuntimeError("Recent error")
        
        # Add exception
        self.notifier.notify_exception("test_source", exception, "error", "Recent Error")
        
        # Wait less than timeout
        time.sleep(0.5)
        
        # Manually trigger cleanup
        self.notifier._cleanup_old_exceptions()
        
        # Exception should still be active
        self.assertTrue(self.notifier.is_exception_active("test_source"))
    
    def test_automatic_cleanup_scheduling(self):
        """Test that cleanup is automatically scheduled."""
        exception = RuntimeError("Test error")
        
        # Add exception (should schedule cleanup)
        self.notifier.notify_exception("test_source", exception, "error", "Test Error")
        
        # Verify cleanup timer is scheduled
        self.assertIsNotNone(self.notifier._cleanup_timer)
        self.assertTrue(self.notifier._cleanup_timer.is_alive())
        
        # Cancel the timer to avoid interference with other tests
        self.notifier._cleanup_timer.cancel()
    
    def test_cleanup_timer_reset_on_new_exception(self):
        """Test that cleanup timer is reset when new exceptions are added."""
        exception1 = RuntimeError("Error 1")
        exception2 = RuntimeError("Error 2")
        
        # Add first exception
        self.notifier.notify_exception("source1", exception1, "error", "Error 1")
        first_timer = self.notifier._cleanup_timer
        
        # Wait a bit
        time.sleep(0.2)
        
        # Add second exception (should reset timer)
        self.notifier.notify_exception("source2", exception2, "warning", "Error 2")
        second_timer = self.notifier._cleanup_timer
        
        # Timer should be different (reset)
        self.assertIsNot(first_timer, second_timer)
        
        # First timer should be cancelled
        self.assertFalse(first_timer.is_alive())
        
        # Second timer should be active
        self.assertTrue(second_timer.is_alive())
        
        # Cancel the timer
        second_timer.cancel()
    
    def test_cleanup_with_deduplication_updates_timestamp(self):
        """Test that deduplicated exceptions update timestamp and avoid premature cleanup."""
        exception = RuntimeError("Repeated error")
        
        # Add exception
        self.notifier.notify_exception("test_source", exception, "error", "Repeated Error")
        
        # Wait most of the timeout period
        time.sleep(0.8)
        
        # Add same exception again (should update timestamp)
        self.notifier.notify_exception("test_source", exception, "error", "Repeated Error")
        
        # Wait a bit more (total time > original timeout, but < timeout from second exception)
        time.sleep(0.5)
        
        # Manually trigger cleanup
        self.notifier._cleanup_old_exceptions()
        
        # Exception should still be active (timestamp was updated)
        self.assertTrue(self.notifier.is_exception_active("test_source"))
        
        # Should have count = 2
        active = self.notifier.get_active_exceptions()
        notification = list(active.values())[0]
        self.assertEqual(notification.count, 2)
    
    def test_cleanup_error_handling(self):
        """Test that cleanup errors don't break the system."""
        exception = RuntimeError("Test error")
        
        # Add exception
        self.notifier.notify_exception("test_source", exception, "error", "Test Error")
        
        # Mock UI callback to raise an error
        self.mock_ui_callback.side_effect = Exception("UI callback error")
        
        # Cleanup should not raise an exception
        try:
            self.notifier._cleanup_old_exceptions()
        except Exception as e:
            self.fail(f"Cleanup raised an exception: {e}")
        
        # System should still be functional
        self.notifier.notify_exception("test_source2", exception, "error", "Test Error 2")
    
    def test_concurrent_cleanup_and_notification(self):
        """Test that cleanup and notification can happen concurrently safely."""
        exception = RuntimeError("Concurrent error")
        
        # Add exception
        self.notifier.notify_exception("test_source", exception, "error", "Concurrent Error")
        
        # Start cleanup in background thread
        cleanup_thread = threading.Thread(target=self.notifier._cleanup_old_exceptions)
        cleanup_thread.start()
        
        # Add more exceptions while cleanup is running
        for i in range(5):
            self.notifier.notify_exception(f"source_{i}", exception, "error", f"Error {i}")
            time.sleep(0.01)
        
        # Wait for cleanup to complete
        cleanup_thread.join()
        
        # System should still be functional
        self.assertTrue(len(self.notifier.get_active_exceptions()) > 0)

if __name__ == '__main__':
    unittest.main()