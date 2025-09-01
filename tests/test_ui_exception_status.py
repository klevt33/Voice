# tests/test_ui_exception_status.py
import unittest
import tkinter as tk
from unittest.mock import Mock, patch

from ui_view import UIView

class TestUIExceptionStatus(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the window during testing
        self.mock_controller = Mock()
        self.ui_view = UIView(self.root, self.mock_controller)
    
    def tearDown(self):
        """Clean up after tests."""
        self.root.destroy()
    
    def test_exception_status_colors_exist(self):
        """Test that exception status colors are defined."""
        status_colors = self.ui_view.status_colors
        
        # Check that new exception status types exist
        self.assertIn("cuda_error", status_colors)
        self.assertIn("audio_error", status_colors)
        self.assertIn("transcription_error", status_colors)
        
        # Check that they have the correct structure (color, message)
        cuda_status = status_colors["cuda_error"]
        self.assertEqual(len(cuda_status), 2)
        self.assertEqual(cuda_status[0], "red")  # Color
        self.assertIn("CUDA Error", cuda_status[1])  # Message
        
        audio_status = status_colors["audio_error"]
        self.assertEqual(len(audio_status), 2)
        self.assertEqual(audio_status[0], "#FF8C00")  # Orange color
        self.assertIn("Audio Error", audio_status[1])  # Message
        
        transcription_status = status_colors["transcription_error"]
        self.assertEqual(len(transcription_status), 2)
        self.assertEqual(transcription_status[0], "red")  # Color
        self.assertIn("Transcription Error", transcription_status[1])  # Message
    
    def test_update_browser_status_with_exception_types(self):
        """Test that update_browser_status works with new exception types."""
        # Test CUDA error status
        self.ui_view.update_browser_status("cuda_error")
        
        # Check that the status indicator and message were updated
        indicator_color = self.ui_view.browser_status_indicator_label.cget("foreground")
        message_text = self.ui_view.status_message_label.cget("text")
        message_color = self.ui_view.status_message_label.cget("foreground")
        
        self.assertEqual(indicator_color, "red")
        self.assertEqual(message_color, "red")
        self.assertIn("CUDA Error", message_text)
        
        # Test audio error status
        self.ui_view.update_browser_status("audio_error")
        
        indicator_color = self.ui_view.browser_status_indicator_label.cget("foreground")
        message_text = self.ui_view.status_message_label.cget("text")
        message_color = self.ui_view.status_message_label.cget("foreground")
        
        self.assertEqual(indicator_color, "#FF8C00")
        self.assertEqual(message_color, "#FF8C00")
        self.assertIn("Audio Error", message_text)
        
        # Test transcription error status
        self.ui_view.update_browser_status("transcription_error")
        
        indicator_color = self.ui_view.browser_status_indicator_label.cget("foreground")
        message_text = self.ui_view.status_message_label.cget("text")
        message_color = self.ui_view.status_message_label.cget("foreground")
        
        self.assertEqual(indicator_color, "red")
        self.assertEqual(message_color, "red")
        self.assertIn("Transcription Error", message_text)
    
    def test_update_browser_status_with_custom_message(self):
        """Test that custom messages override default messages for exception types."""
        custom_message = "CUDA Error - GPU out of memory (3x)"
        
        self.ui_view.update_browser_status("cuda_error", custom_message)
        
        message_text = self.ui_view.status_message_label.cget("text")
        self.assertEqual(message_text, custom_message)
        
        # Color should still be from the status type
        indicator_color = self.ui_view.browser_status_indicator_label.cget("foreground")
        self.assertEqual(indicator_color, "red")

if __name__ == '__main__':
    unittest.main()