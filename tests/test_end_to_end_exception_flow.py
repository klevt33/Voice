# tests/test_end_to_end_exception_flow.py
import unittest
import queue
import threading
import time
import tkinter as tk
from unittest.mock import Mock, patch, MagicMock

from AudioToChat import AudioToChat
from exception_notifier import ExceptionNotifier
from ui_view import UIView

class TestEndToEndExceptionFlow(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Reset exception notifier singleton
        ExceptionNotifier._instance = None
        
        # Create a minimal Tkinter root for testing
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the window during testing
        
        # Mock external dependencies to avoid actual hardware/network calls
        self.patches = []
        
        # Mock PyAudio
        pyaudio_patch = patch('managers.pyaudio.PyAudio')
        self.mock_pyaudio = pyaudio_patch.start()
        self.patches.append(pyaudio_patch)
        
        # Mock browser manager
        browser_patch = patch('managers.BrowserManager')
        self.mock_browser_manager = browser_patch.start()
        self.patches.append(browser_patch)
        
        # Mock audio device utilities
        device_utils_patches = [
            patch('managers.get_default_microphone_info'),
            patch('managers.get_default_speakers_loopback_info'),
            patch('managers.validate_device_info'),
            patch('managers.format_device_info')
        ]
        
        for patch_obj in device_utils_patches:
            mock = patch_obj.start()
            self.patches.append(patch_obj)
            # Set up reasonable defaults
            if 'microphone' in str(patch_obj):
                mock.return_value = {"index": 0, "name": "Test Microphone", "maxInputChannels": 1, "defaultSampleRate": 44100}
            elif 'speakers' in str(patch_obj):
                mock.return_value = {"index": 1, "name": "Test Speakers", "maxInputChannels": 2, "defaultSampleRate": 44100}
            elif 'validate' in str(patch_obj):
                mock.return_value = True
            elif 'format' in str(patch_obj):
                mock.return_value = "Test Device"
        
        # Mock load_single_chat_prompt
        chat_patch = patch('managers.load_single_chat_prompt')
        mock_chat = chat_patch.start()
        mock_chat.return_value = {"url": "test", "init_prompt": "test"}
        self.patches.append(chat_patch)
        
        # Mock TopicRouter
        router_patch = patch('AudioToChat.TopicRouter')
        self.mock_router = router_patch.start()
        self.patches.append(router_patch)
        
        # Mock UIController
        ui_patch = patch('AudioToChat.UIController')
        self.mock_ui_controller = ui_patch.start()
        self.patches.append(ui_patch)
        
        # Set up mock UI controller to track status updates
        self.status_updates = []
        def track_status_update(status_key, message=None):
            self.status_updates.append((status_key, message))
        
        self.mock_ui_controller.return_value.update_browser_status = track_status_update
    
    def tearDown(self):
        """Clean up after tests."""
        # Stop all patches
        for patch_obj in self.patches:
            patch_obj.stop()
        
        # Destroy Tkinter root
        if self.root:
            self.root.destroy()
        
        # Clean up exception notifier
        if hasattr(ExceptionNotifier, '_instance') and ExceptionNotifier._instance:
            if ExceptionNotifier._instance._cleanup_timer:
                ExceptionNotifier._instance._cleanup_timer.cancel()
    
    def test_cuda_error_end_to_end_flow(self):
        """Test complete CUDA error flow from transcription to UI."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Verify exception notifier is initialized
        self.assertIsNotNone(app.service_manager.exception_notifier)
        
        # Simulate CUDA error in transcription
        cuda_error = RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        app.service_manager.exception_notifier.notify_exception(
            "transcription", cuda_error, "error"
        )
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify status update was called
        self.assertTrue(len(self.status_updates) > 0)
        
        # Find CUDA error status update
        cuda_status_update = None
        for status_key, message in self.status_updates:
            if status_key == "cuda_error":
                cuda_status_update = (status_key, message)
                break
        
        self.assertIsNotNone(cuda_status_update)
        self.assertEqual(cuda_status_update[0], "cuda_error")
        self.assertIn("CUDA Error", cuda_status_update[1])
        self.assertIn("GPU out of memory", cuda_status_update[1])
        
        # Verify exception is active
        self.assertTrue(app.service_manager.exception_notifier.is_exception_active("transcription"))
        
        # Simulate recovery (successful transcription)
        app.service_manager.exception_notifier.clear_exception_status("transcription")
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify recovery status update
        recovery_update = None
        for status_key, message in self.status_updates[-3:]:  # Check recent updates
            if "Ready" in str(message):
                recovery_update = (status_key, message)
                break
        
        self.assertIsNotNone(recovery_update)
        
        # Verify exception is no longer active
        self.assertFalse(app.service_manager.exception_notifier.is_exception_active("transcription"))
    
    def test_audio_error_end_to_end_flow(self):
        """Test complete audio error flow from device to UI."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Simulate audio device error
        audio_error = RuntimeError("errno -9999: Unanticipated host error")
        app.service_manager.exception_notifier.notify_exception(
            "audio_device", audio_error, "warning"
        )
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify status update was called
        self.assertTrue(len(self.status_updates) > 0)
        
        # Find audio error status update
        audio_status_update = None
        for status_key, message in self.status_updates:
            if status_key == "audio_error":
                audio_status_update = (status_key, message)
                break
        
        self.assertIsNotNone(audio_status_update)
        self.assertEqual(audio_status_update[0], "audio_error")
        self.assertIn("Audio Device Error", audio_status_update[1])
        
        # Verify exception is active
        self.assertTrue(app.service_manager.exception_notifier.is_exception_active("audio_device"))
        
        # Simulate recovery (successful reconnection)
        app.service_manager.exception_notifier.clear_exception_status("audio_device")
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify exception is no longer active
        self.assertFalse(app.service_manager.exception_notifier.is_exception_active("audio_device"))
    
    def test_multiple_exceptions_priority_handling(self):
        """Test handling of multiple simultaneous exceptions."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Simulate multiple errors
        cuda_error = RuntimeError("CUDA out of memory")
        audio_error = RuntimeError("errno -9999: Unanticipated host error")
        
        app.service_manager.exception_notifier.notify_exception(
            "transcription", cuda_error, "error"
        )
        app.service_manager.exception_notifier.notify_exception(
            "audio_device", audio_error, "warning"
        )
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify both exceptions are active
        self.assertTrue(app.service_manager.exception_notifier.is_exception_active("transcription"))
        self.assertTrue(app.service_manager.exception_notifier.is_exception_active("audio_device"))
        
        # Should have received multiple status updates
        self.assertGreaterEqual(len(self.status_updates), 2)
        
        # Clear one exception
        app.service_manager.exception_notifier.clear_exception_status("transcription")
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify only one exception remains
        self.assertFalse(app.service_manager.exception_notifier.is_exception_active("transcription"))
        self.assertTrue(app.service_manager.exception_notifier.is_exception_active("audio_device"))
        
        # Should show the remaining exception, not "Ready"
        latest_updates = self.status_updates[-2:]
        has_audio_error = any("Audio" in str(message) for _, message in latest_updates)
        self.assertTrue(has_audio_error)
    
    def test_exception_deduplication_in_ui(self):
        """Test that exception deduplication works in the UI."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Clear any initial status updates
        self.status_updates.clear()
        
        # Simulate rapid identical exceptions
        cuda_error = RuntimeError("CUDA out of memory")
        for i in range(5):
            app.service_manager.exception_notifier.notify_exception(
                "transcription", cuda_error, "error", "CUDA Error"
            )
            time.sleep(0.01)  # Small delay
        
        # Process any pending UI updates
        self.root.update()
        
        # Should have received 5 status updates (one for each exception)
        self.assertEqual(len(self.status_updates), 5)
        
        # Last update should show count
        last_update = self.status_updates[-1]
        self.assertIn("(5x)", last_update[1])
        
        # Should only have one active exception
        active = app.service_manager.exception_notifier.get_active_exceptions()
        self.assertEqual(len(active), 1)
        notification = list(active.values())[0]
        self.assertEqual(notification.count, 5)
    
    def test_thread_safe_exception_notification(self):
        """Test that exception notifications work safely from worker threads."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Clear any initial status updates
        self.status_updates.clear()
        
        # Simulate exceptions from multiple threads (like worker threads would do)
        def worker_thread(thread_id):
            for i in range(3):
                error = RuntimeError(f"Thread {thread_id} error {i}")
                app.service_manager.exception_notifier.notify_exception(
                    f"worker_{thread_id}", error, "error", f"Worker {thread_id} Error"
                )
                time.sleep(0.01)
        
        # Start multiple worker threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=worker_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Process any pending UI updates
        self.root.update()
        
        # Should have received status updates from all threads
        self.assertGreaterEqual(len(self.status_updates), 9)  # 3 threads * 3 exceptions each
        
        # Should have active exceptions from all workers
        active = app.service_manager.exception_notifier.get_active_exceptions()
        self.assertGreaterEqual(len(active), 3)
        
        # Verify no exceptions were raised during concurrent access
        for i in range(3):
            self.assertTrue(app.service_manager.exception_notifier.is_exception_active(f"worker_{i}"))
    
    def test_ui_callback_failure_resilience(self):
        """Test that UI callback failures don't break exception notification."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Mock the UI update method to fail
        def failing_ui_update(status_key, message):
            self.status_updates.append((status_key, message))
            raise Exception("UI update failed")
        
        self.mock_ui_controller.return_value.update_browser_status = failing_ui_update
        
        # Simulate exception
        cuda_error = RuntimeError("CUDA out of memory")
        
        # Should not raise an exception despite UI callback failure
        try:
            app.service_manager.exception_notifier.notify_exception(
                "transcription", cuda_error, "error"
            )
        except Exception as e:
            self.fail(f"Exception notification failed due to UI callback error: {e}")
        
        # Exception should still be tracked
        self.assertTrue(app.service_manager.exception_notifier.is_exception_active("transcription"))
        
        # Should have attempted UI update
        self.assertTrue(len(self.status_updates) > 0)
    
    @patch('transcription.get_whisper_model')
    def test_transcription_thread_integration(self, mock_get_model):
        """Test integration with actual transcription thread error handling."""
        # Create AudioToChat instance
        app = AudioToChat()
        
        # Mock the model to raise CUDA error
        cuda_error = RuntimeError("CUDA out of memory")
        mock_model = Mock()
        mock_model.transcribe.side_effect = cuda_error
        mock_get_model.return_value = mock_model
        
        # Import and test transcription thread directly
        from transcription import transcription_thread
        
        audio_queue = queue.Queue()
        transcribed_topics_queue = queue.Queue()
        run_threads_ref = {"active": True}
        
        # Create mock audio segment
        from audio_handler import AudioSegment
        mock_segment = Mock(spec=AudioSegment)
        mock_segment.source = "ME"
        mock_segment.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Clear any initial status updates
        self.status_updates.clear()
        
        # Start transcription thread
        thread = threading.Thread(
            target=transcription_thread,
            args=(audio_queue, transcribed_topics_queue, run_threads_ref, 
                  app.service_manager.exception_notifier),
            daemon=True
        )
        thread.start()
        
        # Wait for thread to initialize
        time.sleep(0.1)
        
        # Add audio segment to trigger error
        audio_queue.put(mock_segment)
        
        # Wait for processing
        time.sleep(0.2)
        
        # Stop thread
        run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Process any pending UI updates
        self.root.update()
        
        # Verify CUDA error was notified
        cuda_status_update = None
        for status_key, message in self.status_updates:
            if status_key == "cuda_error":
                cuda_status_update = (status_key, message)
                break
        
        self.assertIsNotNone(cuda_status_update)
        self.assertIn("GPU out of memory", cuda_status_update[1])

if __name__ == '__main__':
    unittest.main()