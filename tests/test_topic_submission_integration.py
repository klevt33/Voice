#!/usr/bin/env python3
"""
Integration test for topic submission recovery mechanism.

This test simulates the real-world scenario described in the issue:
1. User attempts to submit topics to browser
2. Connection is lost, submission fails
3. Exception is captured and reflected in UI status bar
4. User initiates reconnection
5. Reconnection succeeds
6. Topic submission functionality is restored
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
from unittest.mock import Mock, MagicMock, patch
from selenium.common.exceptions import InvalidSessionIdException

from browser import BrowserManager, SUBMISSION_SUCCESS, SUBMISSION_FAILED_OTHER
from connection_monitor import ConnectionMonitor, ConnectionState
from reconnection_manager import ReconnectionManager


class TestTopicSubmissionIntegration(unittest.TestCase):
    """Integration test for topic submission recovery."""
    
    def setUp(self):
        """Set up test environment."""
        self.chat_config = {
            "url": "https://chatgpt.com",
            "css_selector_input": "textarea",
            "submit_button_selector": "button[type='submit']",
            "prompt_message_content": "Test prompt"
        }
        
        # Track all UI and status updates
        self.ui_updates = []
        self.status_updates = []
        
        def ui_callback(status, topics):
            self.ui_updates.append((status, topics))
            print(f"UI Update: {status}, topics: {len(topics) if topics else 0}")
        
        def status_callback(status, msg):
            self.status_updates.append((status, msg))
            print(f"Status Update: {status}, msg: {msg}")
        
        # Create browser manager
        self.browser_manager = BrowserManager(
            self.chat_config,
            ui_callback,
            status_callback
        )
        
        # Mock the WebDriver components
        self.mock_driver = Mock()
        self.mock_chat_page = Mock()
        
        # Set up successful mocks initially
        self.mock_chat_page.prime_input.return_value = True
        self.mock_chat_page.is_ready_for_input.return_value = SUBMISSION_SUCCESS
        self.mock_chat_page.submit_message.return_value = True
        
        self.browser_manager.driver = self.mock_driver
        self.browser_manager.chat_page = self.mock_chat_page
        
        # Initialize connection monitoring
        self.browser_manager.reconnection_manager = ReconnectionManager(
            self.browser_manager, 
            status_callback
        )
        self.browser_manager.connection_monitor = ConnectionMonitor(
            self.browser_manager,
            status_callback,
            self.browser_manager.reconnection_manager
        )
        
        # Mock other methods
        self.browser_manager.test_connection_health = Mock(return_value=True)
        self.browser_manager.focus_browser_window = Mock()
        self.browser_manager._handle_screenshot_upload = Mock()
        
        # Start communication thread
        self.browser_manager.start_communication_thread()
        time.sleep(0.1)  # Let thread start
    
    def tearDown(self):
        """Clean up test environment."""
        self.browser_manager.stop_communication_thread()
        time.sleep(0.1)
    
    def test_complete_recovery_scenario(self):
        """Test the complete recovery scenario as described in the issue."""
        
        print("\n=== Testing Complete Recovery Scenario ===")
        
        # Step 1: Submit topics successfully (baseline)
        print("\n1. Submitting topics successfully (baseline)...")
        test_topic = {"content": "Test topic", "topic_objects": [Mock()]}
        self.browser_manager.browser_queue.put(test_topic)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify successful submission
        self.assertTrue(len(self.ui_updates) > 0, "Should have UI updates")
        last_ui_status = self.ui_updates[-1][0]
        self.assertEqual(last_ui_status, SUBMISSION_SUCCESS, "First submission should succeed")
        
        # Clear updates for next phase
        self.ui_updates.clear()
        self.status_updates.clear()
        
        # Step 2: Simulate connection loss during topic submission
        print("\n2. Simulating connection loss during topic submission...")
        
        # Prevent automatic reconnection during this phase
        original_attempt_reconnection = self.browser_manager.reconnection_manager.attempt_reconnection
        self.browser_manager.reconnection_manager.attempt_reconnection = Mock(return_value=False)
        
        connection_error = InvalidSessionIdException("Session not found")
        self.mock_chat_page.prime_input.side_effect = connection_error
        
        # Submit topic that will fail
        failed_topic = {"content": "Failed topic", "topic_objects": [Mock()]}
        self.browser_manager.browser_queue.put(failed_topic)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify connection error was detected and UI was updated
        print("Checking UI updates after connection error...")
        self.assertTrue(len(self.status_updates) > 0, "Should have status updates after connection error")
        
        status_keys = [update[0] for update in self.status_updates]
        self.assertIn("connection_lost", status_keys, "Should show connection lost status")
        
        # Verify connection state (may be DISCONNECTED or RECONNECTING due to automatic reconnection)
        connection_state = self.browser_manager.connection_monitor.get_connection_state()
        self.assertIn(
            connection_state,
            [ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING],
            f"Connection should be disconnected or reconnecting, but was {connection_state}"
        )
        
        # Step 3: Simulate manual reconnection
        print("\n3. Simulating manual reconnection...")
        
        # Restore the original reconnection method and set up mocks
        self.browser_manager.reconnection_manager.attempt_reconnection = original_attempt_reconnection
        
        # Mock successful reconnection
        def mock_reinitialize():
            # Reset mocks to simulate successful reconnection
            self.mock_chat_page.prime_input.side_effect = None
            self.mock_chat_page.prime_input.return_value = True
            # Ensure chat_page is restored after reconnection
            self.browser_manager.chat_page = self.mock_chat_page
            return True
        
        self.browser_manager.reinitialize_connection = Mock(side_effect=mock_reinitialize)
        self.browser_manager.new_chat = Mock(return_value=True)
        
        # Clear updates before reconnection
        self.ui_updates.clear()
        self.status_updates.clear()
        
        # Attempt reconnection
        success = self.browser_manager.reconnection_manager.attempt_reconnection()
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify reconnection status updates
        status_keys = [update[0] for update in self.status_updates]
        self.assertIn("reconnecting", status_keys, "Should show reconnecting status")
        self.assertIn("reconnected", status_keys, "Should show reconnected status")
        
        # Verify connection state is restored
        self.assertEqual(
            self.browser_manager.connection_monitor.get_connection_state(),
            ConnectionState.CONNECTED,
            "Connection should be restored after reconnection"
        )
        
        # Step 4: Verify topic submission works after reconnection
        print("\n4. Verifying topic submission works after reconnection...")
        
        # Clear updates for final test
        self.ui_updates.clear()
        self.status_updates.clear()
        
        # Submit new topic after reconnection
        recovery_topic = {"content": "Recovery topic", "topic_objects": [Mock()]}
        self.browser_manager.browser_queue.put(recovery_topic)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify successful submission after recovery
        self.assertTrue(len(self.ui_updates) > 0, "Should have UI updates after recovery")
        final_ui_status = self.ui_updates[-1][0]
        self.assertEqual(final_ui_status, SUBMISSION_SUCCESS, "Topic submission should work after recovery")
        
        # Verify that the mocked methods were called correctly
        self.mock_chat_page.prime_input.assert_called()
        self.mock_chat_page.submit_message.assert_called()
        
        print("\n=== Recovery Scenario Test Complete ===")
        print("✓ Connection error properly detected and reported to UI")
        print("✓ Reconnection successfully restored connection state")
        print("✓ Topic submission functionality recovered after reconnection")
    
    def test_new_thread_button_works_after_reconnection(self):
        """Test that New Thread button works after reconnection (as mentioned in issue)."""
        
        print("\n=== Testing New Thread Button After Reconnection ===")
        
        # Simulate connection loss
        connection_error = InvalidSessionIdException("Session not found")
        self.browser_manager.connection_monitor.last_error = connection_error
        self.browser_manager.connection_monitor.set_connection_state(ConnectionState.DISCONNECTED)
        
        # Mock successful reconnection and new_chat
        self.browser_manager.reinitialize_connection = Mock(return_value=True)
        self.browser_manager.new_chat = Mock(return_value=True)
        
        # Perform reconnection
        success = self.browser_manager.reconnection_manager.attempt_reconnection()
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify that new_chat (New Thread functionality) was called during reconnection
        self.browser_manager.new_chat.assert_called_once()
        
        # Verify connection is restored
        self.assertEqual(
            self.browser_manager.connection_monitor.get_connection_state(),
            ConnectionState.CONNECTED,
            "Connection should be restored"
        )
        
        print("✓ New Thread functionality works after reconnection")


if __name__ == '__main__':
    unittest.main(verbosity=2)