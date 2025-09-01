# tests/test_exception_notifier_edge_cases.py
import unittest
import threading
import time
from unittest.mock import Mock

from exception_notifier import ExceptionNotifier

class TestExceptionNotifierEdgeCases(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create fresh exception notifier instance
        ExceptionNotifier._instance = None
        self.notifier = ExceptionNotifier()
        self.mock_ui_callback = Mock()
        self.notifier.set_ui_update_callback(self.mock_ui_callback)
    
    def tearDown(self):
        """Clean up after tests."""
        if self.notifier._cleanup_timer:
            self.notifier._cleanup_timer.cancel()
    
    def test_ui_callback_exception_handling(self):
        """Test that UI callback exceptions don't break the notifier."""
        # Set up callback that raises an exception
        self.mock_ui_callback.side_effect = Exception("UI callback failed")
        
        exception = RuntimeError("Test error")
        
        # This should not raise an exception
        try:
            self.notifier.notify_exception("test_source", exception, "error", "Test Error")
        except Exception as e:
            self.fail(f"notify_exception raised an exception: {e}")
        
        # Exception should still be tracked internally
        self.assertTrue(self.notifier.is_exception_active("test_source"))
    
    def test_no_ui_callback_set(self):
        """Test behavior when no UI callback is set."""
        # Create notifier without UI callback
        ExceptionNotifier._instance = None
        notifier = ExceptionNotifier()
        
        exception = RuntimeError("Test error")
        
        # Should not raise an exception
        try:
            notifier.notify_exception("test_source", exception, "error", "Test Error")
        except Exception as e:
            self.fail(f"notify_exception raised an exception: {e}")
        
        # Exception should still be tracked
        self.assertTrue(notifier.is_exception_active("test_source"))
    
    def test_invalid_severity_handling(self):
        """Test handling of invalid severity values."""
        exception = RuntimeError("Test error")
        
        # Test various invalid severity values
        invalid_severities = ["invalid", "", None, 123, []]
        
        for invalid_severity in invalid_severities:
            with self.subTest(severity=invalid_severity):
                # Should not raise an exception
                try:
                    self.notifier.notify_exception("test_source", exception, invalid_severity, "Test Error")
                except Exception as e:
                    self.fail(f"notify_exception raised an exception with invalid severity {invalid_severity}: {e}")
                
                # Should default to ERROR severity
                active = self.notifier.get_active_exceptions()
                if active:
                    notification = list(active.values())[-1]  # Get the last one
                    self.assertEqual(notification.severity.value, "error")
                
                # Clear for next test
                self.notifier.clear_exception_status("test_source")
    
    def test_none_exception_handling(self):
        """Test handling when None is passed as exception."""
        # Should handle gracefully
        try:
            self.notifier.notify_exception("test_source", None, "error", "Test Error")
        except Exception as e:
            self.fail(f"notify_exception raised an exception with None exception: {e}")
        
        # Should still create a notification
        self.assertTrue(self.notifier.is_exception_active("test_source"))
    
    def test_empty_source_handling(self):
        """Test handling of empty or invalid source values."""
        exception = RuntimeError("Test error")
        
        invalid_sources = ["", None]
        
        for invalid_source in invalid_sources:
            with self.subTest(source=invalid_source):
                # Should not raise an exception
                try:
                    self.notifier.notify_exception(invalid_source, exception, "error", "Test Error")
                except Exception as e:
                    self.fail(f"notify_exception raised an exception with invalid source {invalid_source}: {e}")
    
    def test_concurrent_access_thread_safety(self):
        """Test thread safety with concurrent access."""
        exception = RuntimeError("Concurrent error")
        
        def worker(worker_id):
            for i in range(10):
                self.notifier.notify_exception(f"source_{worker_id}", exception, "error", f"Error {worker_id}_{i}")
                time.sleep(0.01)
        
        # Start multiple worker threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Should have exceptions from all workers
        active = self.notifier.get_active_exceptions()
        self.assertGreater(len(active), 0)
        
        # No exceptions should have been raised
        # (if there were thread safety issues, we'd likely see exceptions or inconsistent state)
    
    def test_clear_nonexistent_source(self):
        """Test clearing exceptions for a source that doesn't exist."""
        # Should not raise an exception
        try:
            self.notifier.clear_exception_status("nonexistent_source")
        except Exception as e:
            self.fail(f"clear_exception_status raised an exception: {e}")
        
        # Should not affect other exceptions
        exception = RuntimeError("Test error")
        self.notifier.notify_exception("real_source", exception, "error", "Test Error")
        self.assertTrue(self.notifier.is_exception_active("real_source"))
        
        # Clear nonexistent source again
        self.notifier.clear_exception_status("nonexistent_source")
        
        # Real source should still be active
        self.assertTrue(self.notifier.is_exception_active("real_source"))
    
    def test_is_exception_active_nonexistent_source(self):
        """Test checking if exception is active for nonexistent source."""
        # Should return False, not raise an exception
        result = self.notifier.is_exception_active("nonexistent_source")
        self.assertFalse(result)
    
    def test_message_generation_with_various_exceptions(self):
        """Test message generation with various exception types."""
        test_cases = [
            (RuntimeError("CUDA out of memory"), "transcription", "CUDA Error - GPU out of memory"),
            (RuntimeError("CUDA driver version insufficient"), "transcription", "CUDA Error - GPU driver issue"),
            (RuntimeError("GPU device error"), "transcription", "CUDA Error - Transcription unavailable"),
            (RuntimeError("errno -9999"), "audio_device", "Audio Device Error - Check microphone connection"),
            (ValueError("Invalid format"), "transcription", "Transcription Error - Speech processing failed"),
            (Exception("Generic error"), "unknown_source", "Unknown_source Error - Generic error..."),
        ]
        
        for exception, source, expected_message_part in test_cases:
            with self.subTest(exception=str(exception), source=source):
                # Clear previous exceptions
                self.notifier._active_exceptions.clear()
                self.mock_ui_callback.reset_mock()
                
                # Notify exception without custom message (should auto-generate)
                self.notifier.notify_exception(source, exception, "error")
                
                # Check that message was generated correctly
                self.mock_ui_callback.assert_called()
                call_args = self.mock_ui_callback.call_args[0]
                message = call_args[1]
                
                # Should contain expected message part
                self.assertIn(expected_message_part.split(" - ")[0], message)
    
    def test_cleanup_timer_cancellation_on_shutdown(self):
        """Test that cleanup timer is properly cancelled."""
        exception = RuntimeError("Test error")
        
        # Add exception to start timer
        self.notifier.notify_exception("test_source", exception, "error", "Test Error")
        
        # Verify timer is running
        self.assertIsNotNone(self.notifier._cleanup_timer)
        self.assertTrue(self.notifier._cleanup_timer.is_alive())
        
        # Cancel timer (simulating shutdown)
        self.notifier._cleanup_timer.cancel()
        
        # Timer should be cancelled
        self.assertFalse(self.notifier._cleanup_timer.is_alive())
    
    def test_large_number_of_exceptions(self):
        """Test handling of a large number of exceptions."""
        # Add many exceptions
        for i in range(100):
            exception = RuntimeError(f"Error {i}")
            self.notifier.notify_exception(f"source_{i % 10}", exception, "error", f"Error {i}")
        
        # Should handle gracefully
        active = self.notifier.get_active_exceptions()
        self.assertGreater(len(active), 0)
        self.assertLessEqual(len(active), 100)  # Some might be deduplicated
        
        # System should still be responsive
        new_exception = RuntimeError("New error")
        self.notifier.notify_exception("new_source", new_exception, "error", "New Error")
        self.assertTrue(self.notifier.is_exception_active("new_source"))
    
    def test_exception_in_cleanup_thread(self):
        """Test that exceptions in cleanup thread don't break the system."""
        exception = RuntimeError("Test error")
        
        # Add exception
        self.notifier.notify_exception("test_source", exception, "error", "Test Error")
        
        # Mock the cleanup method to raise an exception
        original_cleanup = self.notifier._cleanup_old_exceptions
        def failing_cleanup():
            raise Exception("Cleanup failed")
        
        self.notifier._cleanup_old_exceptions = failing_cleanup
        
        # Trigger cleanup - should not propagate exception
        try:
            # Start cleanup in thread (as it would normally run)
            cleanup_thread = threading.Thread(target=self.notifier._cleanup_old_exceptions)
            cleanup_thread.start()
            cleanup_thread.join()
        except Exception as e:
            self.fail(f"Cleanup thread exception propagated: {e}")
        
        # Restore original method
        self.notifier._cleanup_old_exceptions = original_cleanup
        
        # System should still be functional
        self.notifier.notify_exception("test_source2", exception, "error", "Test Error 2")
        self.assertTrue(self.notifier.is_exception_active("test_source2"))

if __name__ == '__main__':
    unittest.main()