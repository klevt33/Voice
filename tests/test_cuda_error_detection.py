# tests/test_cuda_error_detection.py
import unittest
import queue
import threading
import time
from unittest.mock import Mock, patch

from transcription import transcription_thread
from exception_notifier import ExceptionNotifier

class TestCUDAErrorDetection(unittest.TestCase):
    
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
    def test_cuda_out_of_memory_error(self, mock_get_model):
        """Test CUDA out of memory error detection."""
        # Mock the model to raise a CUDA out of memory error
        cuda_error = RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        mock_model = Mock()
        mock_model.transcribe.side_effect = cuda_error
        mock_get_model.return_value = mock_model
        
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
        
        # Create a mock audio segment
        from audio_handler import AudioSegment
        mock_segment = Mock(spec=AudioSegment)
        mock_segment.source = "ME"
        mock_segment.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Add audio segment to queue
        self.audio_queue.put(mock_segment)
        
        # Wait for processing
        time.sleep(0.2)
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Check that CUDA error was notified
        self.mock_ui_callback.assert_called()
        call_args = self.mock_ui_callback.call_args[0]
        self.assertEqual(call_args[0], "cuda_error")
        self.assertIn("GPU out of memory", call_args[1])
    
    @patch('transcription.get_whisper_model')
    def test_cuda_driver_error(self, mock_get_model):
        """Test CUDA driver error detection."""
        # Mock the model to raise a CUDA driver error
        cuda_error = RuntimeError("CUDA driver version is insufficient for CUDA runtime version")
        mock_model = Mock()
        mock_model.transcribe.side_effect = cuda_error
        mock_get_model.return_value = mock_model
        
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
        
        # Create a mock audio segment
        from audio_handler import AudioSegment
        mock_segment = Mock(spec=AudioSegment)
        mock_segment.source = "ME"
        mock_segment.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Add audio segment to queue
        self.audio_queue.put(mock_segment)
        
        # Wait for processing
        time.sleep(0.2)
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Check that CUDA driver error was notified
        self.mock_ui_callback.assert_called()
        call_args = self.mock_ui_callback.call_args[0]
        self.assertEqual(call_args[0], "cuda_error")
        self.assertIn("GPU driver issue", call_args[1])
    
    @patch('transcription.get_whisper_model')
    def test_general_cuda_error(self, mock_get_model):
        """Test general CUDA error detection."""
        # Mock the model to raise a general CUDA error
        cuda_error = RuntimeError("CUDA error: device-side assert triggered")
        mock_model = Mock()
        mock_model.transcribe.side_effect = cuda_error
        mock_get_model.return_value = mock_model
        
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
        
        # Create a mock audio segment
        from audio_handler import AudioSegment
        mock_segment = Mock(spec=AudioSegment)
        mock_segment.source = "ME"
        mock_segment.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Add audio segment to queue
        self.audio_queue.put(mock_segment)
        
        # Wait for processing
        time.sleep(0.2)
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Check that general CUDA error was notified
        self.mock_ui_callback.assert_called()
        call_args = self.mock_ui_callback.call_args[0]
        self.assertEqual(call_args[0], "cuda_error")
        self.assertIn("Transcription unavailable", call_args[1])
    
    @patch('transcription.get_whisper_model')
    def test_non_cuda_error(self, mock_get_model):
        """Test that non-CUDA errors are handled differently."""
        # Mock the model to raise a non-CUDA error
        general_error = ValueError("Invalid audio format")
        mock_model = Mock()
        mock_model.transcribe.side_effect = general_error
        mock_get_model.return_value = mock_model
        
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
        
        # Create a mock audio segment
        from audio_handler import AudioSegment
        mock_segment = Mock(spec=AudioSegment)
        mock_segment.source = "ME"
        mock_segment.get_wav_bytes.return_value = b"fake_audio_data"
        
        # Add audio segment to queue
        self.audio_queue.put(mock_segment)
        
        # Wait for processing
        time.sleep(0.2)
        
        # Stop the thread
        self.run_threads_ref["active"] = False
        thread.join(timeout=1)
        
        # Check that general transcription error was notified
        self.mock_ui_callback.assert_called()
        call_args = self.mock_ui_callback.call_args[0]
        self.assertEqual(call_args[0], "transcription_error")
        self.assertIn("Processing failed", call_args[1])

if __name__ == '__main__':
    unittest.main()