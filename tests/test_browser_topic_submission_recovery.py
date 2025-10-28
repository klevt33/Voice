#!/usr/bin/env python3
"""
Test browser topic submission recovery after connection loss.

This test verifies that:
1. When topic submission fails due to connection loss, the exception is reflected in the UI status bar
2. After successful reconnection, topic submission functionality is restored
3. The recovery mechanism properly handles the queue state and communication thread
"""

import unittest
import threading
import time
import queue
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Add parent directory to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the modules we're testing
from browser import BrowserManager, SUBMISSION_SUCCESS, SUBMISSION_FAILED_OTHER
from connection_monitor import ConnectionMonitor, ConnectionState
from reconnection_manager import ReconnectionManager
from selenium.common.exceptions import InvalidSessionIdException


class TestBrowserTopicSubmissionRecovery(unittest.TestCase):
    """Test browser topic submission recovery after connection loss."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.chat_config = {
            "url": "https://chatgpt.com",
            "css_selector_input": "textarea",
            "submit_button_selector": "button[type='submit']",
            "prompt_message_content": "Test prompt"
        }
        
        # Mock UI callback to track status updates
        self.ui_updates = []
        self.ui_callback = Mock(side_effect=lambda status, topics: self.ui_updates.append((status, topics)))
        
        # Mock status callback for connection status
        self.status_updates = []
        self.status_callback = Mock(side_effect=lambda status, msg: self.status_updates.append((status, msg)))
        
        # Create browser manager with mocked driver
        self.browser_manager = BrowserManager(
            self.chat_config, 
            self.ui_callback, 
            self.status_callback
        )
        
        # Mock the driver and chat_page
        self.mock_driver = Mock()
        self.mock_chat_page = Mock()
        self.browser_manager.driver = self.mock_driver
        self.browser_manager.chat_page = self.mock_chat_page
        
        # Set up connection monitor and reconnection manager
        self.browser_manager.reconnection_manager = ReconnectionManager(self.browser_manager, self.status_callback)
        self.browser_manager.connection_monitor = ConnectionMonitor(
            self.browser_manager, 
            self.status_callback, 
            self.browser_manager.reconnection_manager
        )
        
        # Start the communication thread
        self.browser_manager.start_communication_thread()
        
        # Give the thread a moment to start
        time.sleep(0.1)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.browser_manager.stop_communication_thread()
        time.sleep(0.1)
    
    def test_connection_error_during_submission_shows_in_ui(self):
        """Test that connection errors during topic submission are reflected in the UI status bar."""
        
        # Set up the mock to simulate connection error during prime_input
        connection_error = InvalidSessionIdException("Session not found")
        self.mock_chat_page.prime_input.side_effect = connection_error
        
        # Mock other methods to avoid issues
        self.mock_chat_page.is_ready_for_input.return_value = SUBMISSION_SUCCESS
        self.browser_manager.test_connection_health = Mock(return_value=True)
        self.browser_manager.focus_browser_window = Mock()
        
        # Submit a topic
        test_topic = {"content": "Test topic", "topic_objects": []}
        self.browser_manager.browser_queue.put(test_topic)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify that UI was updated with connection error status
        self.assertTrue(len(self.status_updates) > 0, "Status callback should have been called")
        
        # Check that connection_lost status was sent
        status_keys = [update[0] for update in self.status_updates]
        self.assertIn("connection_lost", status_keys, "UI should show connection lost status")
        
        # Verify that the UI callback was called with failure status
        self.assertTrue(len(self.ui_updates) > 0, "UI callback should have been called")
        ui_status = self.ui_updates[-1][0]  # Get the last status update
        self.assertEqual(ui_status, SUBMISSION_FAILED_OTHER, "UI should show submission failed status")
    
    def test_topic_submission_recovery_after_reconnection(self):
        """Test that topic submission works after successful reconnection."""
        
        # First, simulate a connection error
        connection_error = InvalidSessionIdException("Session not found")
        self.mock_chat_page.prime_input.side_effect = connection_error
        
        # Mock successful reconnection
        def mock_reinitialize():
            # Reset the mock to simulate successful reconnection
            self.mock_chat_page.prime_input.side_effect = None
            self.mock_chat_page.prime_input.return_value = True
            self.mock_chat_page.submit_message.return_value = True
            return True
        
        self.browser_manager.reinitialize_connection = Mock(side_effect=mock_reinitialize)
        self.browser_manager.new_chat = Mock(return_value=True)
        self.browser_manager.test_connection_health = Mock(return_value=True)
        self.browser_manager.focus_browser_window = Mock()
        
        # Set up other mocks
        self.mock_chat_page.is_ready_for_input.return_value = SUBMISSION_SUCCESS
        self.browser_manager._handle_screenshot_upload = Mock()
        
        # Submit first topic (should fail due to connection error)
        test_topic1 = {"content": "Test topic 1", "topic_objects": []}
        self.browser_manager.browser_queue.put(test_topic1)
        
        # Wait for the error to be processed
        time.sleep(0.5)
        
        # Verify connection error was detected
        self.assertEqual(
            self.browser_manager.connection_monitor.get_connection_state(), 
            ConnectionState.DISCONNECTED
        )
        
        # Simulate successful reconnection
        success = self.browser_manager.reconnection_manager.attempt_reconnection()
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify connection state is restored
        self.assertEqual(
            self.browser_manager.connection_monitor.get_connection_state(), 
            ConnectionState.CONNECTED
        )
        
        # Clear previous UI updates to focus on post-reconnection behavior
        self.ui_updates.clear()
        self.status_updates.clear()
        
        # Submit second topic (should succeed after reconnection)
        test_topic2 = {"content": "Test topic 2", "topic_objects": []}
        self.browser_manager.browser_queue.put(test_topic2)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify that the second submission succeeded
        self.assertTrue(len(self.ui_updates) > 0, "UI should be updated after successful submission")
        final_status = self.ui_updates[-1][0]
        self.assertEqual(final_status, SUBMISSION_SUCCESS, "Topic submission should succeed after reconnection")
        
        # Verify that prime_input and submit_message were called for the second topic
        self.mock_chat_page.prime_input.assert_called()
        self.mock_chat_page.submit_message.assert_called()
    
    def test_communication_thread_recovery(self):
        """Test that the communication thread is properly managed during reconnection."""
        
        # Verify thread is initially running
        self.assertTrue(
            self.browser_manager.run_threads_ref.get("active", False),
            "Communication thread should be active initially"
        )
        
        # Simulate thread stopping (shouldn't happen in normal operation, but test recovery)
        self.browser_manager.run_threads_ref["active"] = False
        
        # Mock successful reconnection components
        self.browser_manager.reinitialize_connection = Mock(return_value=True)
        self.browser_manager.new_chat = Mock(return_value=True)
        self.browser_manager.test_connection_health = Mock(return_value=True)
        
        # Attempt reconnection
        success = self.browser_manager.reconnection_manager.attempt_reconnection()
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify that communication thread is restarted if it was stopped
        # The _reset_communication_state method should handle this
        time.sleep(0.1)  # Give time for thread restart
        
        # Check that the thread reference is active again
        self.assertTrue(
            self.browser_manager.run_threads_ref.get("active", False),
            "Communication thread should be restarted after reconnection"
        )
    
    def test_queue_preservation_during_reconnection(self):
        """Test that pending queue items are preserved during reconnection."""
        
        # Add multiple items to the queue
        test_topics = [
            {"content": "Topic 1", "topic_objects": []},
            {"content": "Topic 2", "topic_objects": []},
            {"content": "Topic 3", "topic_objects": []}
        ]
        
        for topic in test_topics:
            self.browser_manager.browser_queue.put(topic)
        
        # Verify queue has items
        initial_queue_size = self.browser_manager.browser_queue.qsize()
        self.assertEqual(initial_queue_size, 3, "Queue should have 3 items")
        
        # Simulate connection error that prevents processing
        self.browser_manager.connection_monitor.set_connection_state(ConnectionState.DISCONNECTED)
        
        # Mock successful reconnection
        self.browser_manager.reinitialize_connection = Mock(return_value=True)
        self.browser_manager.new_chat = Mock(return_value=True)
        self.browser_manager.test_connection_health = Mock(return_value=True)
        
        # Attempt reconnection
        success = self.browser_manager.reconnection_manager.attempt_reconnection()
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify queue items are preserved
        final_queue_size = self.browser_manager.browser_queue.qsize()
        self.assertEqual(final_queue_size, 3, "Queue items should be preserved during reconnection")
        
        # Verify that the preserve_queue_state method works
        preserved_count = self.browser_manager.preserve_queue_state()
        self.assertEqual(preserved_count, 3, "preserve_queue_state should return correct count")


if __name__ == '__main__':
    unittest.main()