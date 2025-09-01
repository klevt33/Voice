# tests/test_cuda_recovery_detection.py
import unittest
import queue
import threading
import time
from unittest.mock import Mock, patch

from transcription import transcription_thread
from exception_notifier import ExceptionNotifier

class TestCUDARecoveryDetection(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Create fresh exception notifier instance
        ExceptionNotifier._instance = None
        self.exception_notifier = ExceptionNotifier()
        self.mock_ui_callback = Mock()
        self.exception_notifier.set_ui_update_callback(self.mock_ui_callback)
        
        # Create queues and thread control
        self.audio_queue = queue.Queue()
        self.transcribed_topics_queue = queue.Queue()
        self.run_threads_ref = {"active": True}
    
    def tearDown(self):
        """Clean up after tests."""
        self.run_threads_ref["active"] = False
        if self.exception_notifier._cleanup_timer:
            self.exception_notifier._cleanup_timer.cancel()
    
    @patch('transcription.get_whisper_model')
    def test_cuda_error_recovery(self, mock_get_model):
        """Test that CUDA error status is cleared on successful transcription."""
        # Mock the model to first fail with CUDA error, then succeed
        cuda_error = RuntimeError("CUDA out of memory")
        
        # Create mock segments for transcription results
        mock_segment_result = Mock()
        mock_segment_result.text = "Hello world"
        
        mock_model = Mock()
        mock_get_model.return_value = mock_model
        
        # First call fails with CUDA error, second succeeds
        mock_model.transcribe.side_effect = [
            cuda_error,  # First call fails
            ([mock_segment_result], Mock())  # Second call succeeds
        ]
        
        # Start transcription thread
        thread = threading.Thread(
            target=transcription_thread,
            args=(self.audio_queue, self.transcribed_topics_queue, 
                  self.run_threads_ref, self.exception_notifier),
            daemon=True
        )
        thread.start()
        
        # Wait a moment for thread to initialize
        time.sleep(0.1)
        
        # Create mock audio segments
        from audio_handler import AudioSegment
        mock_segment1 = Mock(spec=AudioSegment)
        mock_segment1.source = "ME"
        mock_segment1.get_wav_bytes.return_value = b"fake_audio_data"
        
        mock_segment2 = Mock(spec=AudioSegment)
        mock_segment2.source = "ME"
        mock_segment2.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Add first segment (should fail with CUDA error)
        self.audio_queue.put(mock_segment1)
        time.sleep(0.2)
        
        # Verify CUDA error was notified
        self.assertTrue(self.exception_notifier.is_exception_active("transcription"))
        cuda_error_call = None
        for call in self.mock_ui_callback.call_args_list:
            if call[0][0] == "cuda_error":
                cuda_error_call = call
                break
        self.assertIsNotNone(cuda_error_call)
        
        # Reset mock to track recovery
        self.mock_ui_callback.reset_mock()
        
        # Add second segment (should succeed and clear error)
        self.audio_queue.put(mock_segment2)
        time.sleep(0.2)
        
        # Verify that transcription error status was cleared
        self.assertFalse(self.exception_notifier.is_exception_active("transcription"))
        
        # Check that a topic was created
        self.assertFalse(self.transcribed_topics_queue.empty())
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Verify recovery status update was called
        recovery_call = None
        for call in self.mock_ui_callback.call_args_list:
            if len(call[0]) >= 2 and "Ready" in call[0][1]:
                recovery_call = call
                break
        self.assertIsNotNone(recovery_call, "Recovery status update should have been called")
    
    @patch('transcription.get_whisper_model')
    def test_multiple_error_recovery(self, mock_get_model):
        """Test recovery when there are multiple active exceptions."""
        # Simulate having both transcription and another type of error
        cuda_error = RuntimeError("CUDA out of memory")
        
        # Create mock segments for transcription results
        mock_segment_result = Mock()
        mock_segment_result.text = "Hello world"
        
        mock_model = Mock()
        mock_get_model.return_value = mock_model
        mock_model.transcribe.return_value = ([mock_segment_result], Mock())
        
        # Add a non-transcription exception first
        self.exception_notifier.notify_exception("audio_device", Exception("Audio error"), "warning")
        
        # Add a transcription exception
        self.exception_notifier.notify_exception("transcription", cuda_error, "error")
        
        # Verify both are active
        self.assertTrue(self.exception_notifier.is_exception_active("transcription"))
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        
        # Start transcription thread
        thread = threading.Thread(
            target=transcription_thread,
            args=(self.audio_queue, self.transcribed_topics_queue, 
                  self.run_threads_ref, self.exception_notifier),
            daemon=True
        )
        thread.start()
        
        # Wait a moment for thread to initialize
        time.sleep(0.1)
        
        # Create mock audio segment
        from audio_handler import AudioSegment
        mock_segment = Mock(spec=AudioSegment)
        mock_segment.source = "ME"
        mock_segment.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Reset mock to track recovery
        self.mock_ui_callback.reset_mock()
        
        # Add segment (should succeed and clear transcription error only)
        self.audio_queue.put(mock_segment)
        time.sleep(0.2)
        
        # Verify that only transcription error was cleared
        self.assertFalse(self.exception_notifier.is_exception_active("transcription"))
        self.assertTrue(self.exception_notifier.is_exception_active("audio_device"))
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Should still show the remaining audio error, not "Ready"
        latest_call = self.mock_ui_callback.call_args
        if latest_call:
            self.assertNotIn("Ready", latest_call[0][1])

if __name__ == '__main__':
    unittest.main()