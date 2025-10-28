#!/usr/bin/env python3
"""
Simple test for topic submission recovery mechanism.

This test verifies the key fixes:
1. Connection errors during topic submission are properly reported to UI
2. Recovery mechanism properly handles reconnection state
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock, MagicMock
from connection_monitor import ConnectionMonitor, ConnectionState
from reconnection_manager import ReconnectionManager
from selenium.common.exceptions import InvalidSessionIdException


class TestTopicSubmissionRecoverySimple(unittest.TestCase):
    """Simple test for topic submission recovery mechanism."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock browser manager
        self.browser_manager = Mock()
        self.browser_manager.driver = Mock()
        self.browser_manager.chat_page = Mock()
        self.browser_manager.browser_queue = Mock()
        self.browser_manager.run_threads_ref = {"active": True}
        
        # Track UI updates
        self.ui_updates = []
        self.ui_callback = Mock(side_effect=lambda status, msg: self.ui_updates.append((status, msg)))
        
        # Create connection monitor
        self.connection_monitor = ConnectionMonitor(
            self.browser_manager, 
            self.ui_callback
        )
        
        # Create reconnection manager
        self.reconnection_manager = ReconnectionManager(
            self.browser_manager,
            self.ui_callback
        )
        
        # Link them together
        self.connection_monitor.reconnection_manager = self.reconnection_manager
        self.browser_manager.connection_monitor = self.connection_monitor
        self.browser_manager.reconnection_manager = self.reconnection_manager
    
    def test_connection_error_triggers_ui_update(self):
        """Test that connection errors trigger proper UI updates."""
        
        # Mock the reconnection manager to prevent automatic reconnection during test
        self.reconnection_manager.is_reconnection_in_progress = Mock(return_value=True)
        
        # Create a connection error
        connection_error = InvalidSessionIdException("Session not found")
        
        # Verify the error is detected as a connection error
        self.assertTrue(
            self.connection_monitor.is_connection_error(connection_error),
            "InvalidSessionIdException should be detected as connection error"
        )
        
        # Simulate the connection monitor detecting the error
        try:
            # This simulates what happens in execute_with_monitoring
            raise connection_error
        except Exception as e:
            if self.connection_monitor.is_connection_error(e):
                self.connection_monitor._handle_connection_loss()
        
        # Give a moment for any threading operations
        import time
        time.sleep(0.1)
        
        # Verify UI was updated
        self.assertTrue(len(self.ui_updates) > 0, "UI should be updated when connection error occurs")
        
        # Check that connection_lost status was sent
        status_keys = [update[0] for update in self.ui_updates]
        self.assertIn("connection_lost", status_keys, "UI should show connection lost status")
        
        # Verify connection state changed
        self.assertEqual(
            self.connection_monitor.get_connection_state(),
            ConnectionState.DISCONNECTED,
            "Connection state should be DISCONNECTED after error"
        )
    
    def test_reconnection_state_management(self):
        """Test that reconnection properly manages connection state."""
        
        # Start in disconnected state
        self.connection_monitor.set_connection_state(ConnectionState.DISCONNECTED)
        
        # Mock successful reconnection components
        self.browser_manager.reinitialize_connection = Mock(return_value=True)
        self.browser_manager.new_chat = Mock(return_value=True)
        self.browser_manager.test_connection_health = Mock(return_value=True)
        self.browser_manager.start_communication_thread = Mock()
        
        # Clear previous UI updates
        self.ui_updates.clear()
        
        # Attempt reconnection
        success = self.reconnection_manager.attempt_reconnection()
        
        # Verify reconnection succeeded
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify connection state is restored
        self.assertEqual(
            self.connection_monitor.get_connection_state(),
            ConnectionState.CONNECTED,
            "Connection state should be CONNECTED after successful reconnection"
        )
        
        # Verify UI updates were sent
        status_keys = [update[0] for update in self.ui_updates]
        self.assertIn("reconnecting", status_keys, "UI should show reconnecting status")
        self.assertIn("reconnected", status_keys, "UI should show reconnected status")
    
    def test_multiple_connection_errors_handled(self):
        """Test that multiple connection errors are properly handled."""
        
        # Mock the reconnection manager to prevent automatic reconnection during test
        self.reconnection_manager.is_reconnection_in_progress = Mock(return_value=True)
        
        # Clear any existing updates
        self.ui_updates.clear()
        
        # Simulate multiple connection errors
        for i in range(3):
            connection_error = InvalidSessionIdException(f"Session error {i}")
            
            try:
                raise connection_error
            except Exception as e:
                if self.connection_monitor.is_connection_error(e):
                    self.connection_monitor._handle_connection_loss()
        
        # Give a moment for any threading operations
        import time
        time.sleep(0.1)
        
        # Verify UI was updated (should handle multiple calls gracefully)
        self.assertTrue(len(self.ui_updates) > 0, "UI should be updated for connection errors")
        
        # Verify connection state is still disconnected
        self.assertEqual(
            self.connection_monitor.get_connection_state(),
            ConnectionState.DISCONNECTED,
            "Connection state should remain DISCONNECTED"
        )
    
    def test_communication_thread_restart_detection(self):
        """Test that communication thread restart is properly detected."""
        
        # Simulate thread being stopped
        self.browser_manager.run_threads_ref["active"] = False
        
        # Mock successful reconnection
        self.browser_manager.reinitialize_connection = Mock(return_value=True)
        self.browser_manager.new_chat = Mock(return_value=True)
        self.browser_manager.test_connection_health = Mock(return_value=True)
        self.browser_manager.start_communication_thread = Mock()
        
        # Attempt reconnection
        success = self.reconnection_manager.attempt_reconnection()
        self.assertTrue(success, "Reconnection should succeed")
        
        # Verify that start_communication_thread was called to restart the thread
        self.browser_manager.start_communication_thread.assert_called_once()


if __name__ == '__main__':
    unittest.main()