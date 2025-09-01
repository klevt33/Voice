#!/usr/bin/env python3
"""
Unit tests for browser reconnection functionality.
Tests connection monitoring, error detection, and reconnection flow.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import logging
from datetime import datetime

# Import the modules we're testing
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connection_monitor import ConnectionMonitor, ConnectionState
from reconnection_manager import ReconnectionManager
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)

class TestConnectionMonitor(unittest.TestCase):
    """Test cases for ConnectionMonitor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_browser_manager = Mock()
        self.mock_ui_callback = Mock()
        self.mock_reconnection_manager = Mock()
        
        self.connection_monitor = ConnectionMonitor(
            self.mock_browser_manager,
            self.mock_ui_callback,
            self.mock_reconnection_manager
        )
    
    def test_connection_error_detection_invalid_session(self):
        """Test that InvalidSessionIdException is correctly identified as connection error."""
        error = InvalidSessionIdException("invalid session id")
        self.assertTrue(self.connection_monitor.is_connection_error(error))
    
    def test_connection_error_detection_webdriver_session_deleted(self):
        """Test that WebDriverException with 'session deleted' is identified as connection error."""
        error = WebDriverException("session deleted as the browser has closed")
        self.assertTrue(self.connection_monitor.is_connection_error(error))
    
    def test_connection_error_detection_webdriver_invalid_session(self):
        """Test that WebDriverException with 'invalid session id' is identified as connection error."""
        error = WebDriverException("invalid session id")
        self.assertTrue(self.connection_monitor.is_connection_error(error))
    
    def test_connection_error_detection_non_connection_error(self):
        """Test that non-connection errors are not identified as connection errors."""
        error = Exception("Some other error")
        self.assertFalse(self.connection_monitor.is_connection_error(error))
        
        webdriver_error = WebDriverException("Element not found")
        self.assertFalse(self.connection_monitor.is_connection_error(webdriver_error))
    
    def test_execute_with_monitoring_success(self):
        """Test that successful operations return their result."""
        mock_operation = Mock(return_value="success")
        
        result = self.connection_monitor.execute_with_monitoring(mock_operation, "arg1", kwarg1="value1")
        
        self.assertEqual(result, "success")
        mock_operation.assert_called_once_with("arg1", kwarg1="value1")
        self.mock_ui_callback.assert_not_called()
    
    def test_execute_with_monitoring_connection_error(self):
        """Test that connection errors trigger recovery process."""
        connection_error = InvalidSessionIdException("invalid session id")
        mock_operation = Mock(side_effect=connection_error)
        
        with self.assertRaises(InvalidSessionIdException):
            self.connection_monitor.execute_with_monitoring(mock_operation)
        
        # Verify that connection loss was handled
        self.mock_ui_callback.assert_called_once_with("connection_lost", None)
        self.mock_reconnection_manager.attempt_reconnection.assert_called_once()
    
    def test_execute_with_monitoring_non_connection_error(self):
        """Test that non-connection errors are re-raised without triggering recovery."""
        non_connection_error = ValueError("Some other error")
        mock_operation = Mock(side_effect=non_connection_error)
        
        with self.assertRaises(ValueError):
            self.connection_monitor.execute_with_monitoring(mock_operation)
        
        # Verify that connection loss handling was not triggered
        self.mock_ui_callback.assert_not_called()
        self.mock_reconnection_manager.attempt_reconnection.assert_not_called()
    
    def test_connection_state_transitions(self):
        """Test that connection state transitions are properly tracked."""
        # Initial state should be CONNECTED
        self.assertEqual(self.connection_monitor.get_connection_state(), ConnectionState.CONNECTED)
        
        # Simulate connection loss
        connection_error = InvalidSessionIdException("invalid session id")
        mock_operation = Mock(side_effect=connection_error)
        
        with self.assertRaises(InvalidSessionIdException):
            self.connection_monitor.execute_with_monitoring(mock_operation)
        
        # State should now be DISCONNECTED
        self.assertEqual(self.connection_monitor.get_connection_state(), ConnectionState.DISCONNECTED)


class TestReconnectionManager(unittest.TestCase):
    """Test cases for ReconnectionManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_browser_manager = Mock()
        self.mock_ui_callback = Mock()
        
        # Mock the browser manager methods
        self.mock_browser_manager.cleanup_driver = Mock()
        self.mock_browser_manager.reinitialize_connection = Mock(return_value=True)
        self.mock_browser_manager.new_chat = Mock(return_value=True)
        self.mock_browser_manager.test_connection_health = Mock(return_value=True)
        self.mock_browser_manager.connection_monitor = Mock()
        
        self.reconnection_manager = ReconnectionManager(
            self.mock_browser_manager,
            self.mock_ui_callback
        )
        
        # Set shorter delays for testing
        self.reconnection_manager.base_delay = 0.01  # 10ms for fast tests
        self.reconnection_manager.max_retries = 2
    
    def test_successful_reconnection_first_attempt(self):
        """Test successful reconnection on first attempt."""
        result = self.reconnection_manager.attempt_reconnection()
        
        self.assertTrue(result)
        self.mock_ui_callback.assert_any_call("reconnecting", None)
        self.mock_browser_manager.cleanup_driver.assert_called_once()
        self.mock_browser_manager.reinitialize_connection.assert_called_once()
        self.mock_browser_manager.new_chat.assert_called_once()
        self.mock_browser_manager.test_connection_health.assert_called_once()
    
    def test_failed_reconnection_all_attempts(self):
        """Test failed reconnection after all attempts."""
        # Make reinitialize_connection fail
        self.mock_browser_manager.reinitialize_connection.return_value = False
        
        result = self.reconnection_manager.attempt_reconnection()
        
        self.assertFalse(result)
        self.mock_ui_callback.assert_any_call("reconnecting", None)
        self.mock_ui_callback.assert_any_call("connection_failed", None)
        
        # Should have tried max_retries times
        self.assertEqual(self.mock_browser_manager.cleanup_driver.call_count, self.reconnection_manager.max_retries)
    
    def test_reconnection_with_retries(self):
        """Test reconnection that succeeds on second attempt."""
        # Make first attempt fail, second succeed
        self.mock_browser_manager.reinitialize_connection.side_effect = [False, True]
        
        result = self.reconnection_manager.attempt_reconnection()
        
        self.assertTrue(result)
        # Should have tried twice
        self.assertEqual(self.mock_browser_manager.cleanup_driver.call_count, 2)
        self.assertEqual(self.mock_browser_manager.reinitialize_connection.call_count, 2)
    
    def test_concurrent_reconnection_attempts(self):
        """Test that concurrent reconnection attempts are handled properly."""
        # First call should proceed, second should be skipped
        self.reconnection_manager.is_reconnecting = True
        
        result = self.reconnection_manager.attempt_reconnection()
        
        self.assertFalse(result)
        # No browser operations should have been called
        self.mock_browser_manager.cleanup_driver.assert_not_called()


class TestBrowserReconnectionIntegration(unittest.TestCase):
    """Integration tests for browser reconnection flow."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.mock_ui_callback = Mock()
        self.mock_browser_manager = Mock()
        
        # Create real instances with mocked dependencies
        self.reconnection_manager = ReconnectionManager(
            self.mock_browser_manager,
            self.mock_ui_callback
        )
        
        self.connection_monitor = ConnectionMonitor(
            self.mock_browser_manager,
            self.mock_ui_callback,
            self.reconnection_manager
        )
        
        # Set up browser manager mocks
        self.mock_browser_manager.cleanup_driver = Mock()
        self.mock_browser_manager.reinitialize_connection = Mock(return_value=True)
        self.mock_browser_manager.new_chat = Mock(return_value=True)
        self.mock_browser_manager.test_connection_health = Mock(return_value=True)
        self.mock_browser_manager.connection_monitor = self.connection_monitor
        
        # Fast reconnection for tests
        self.reconnection_manager.base_delay = 0.01
        self.reconnection_manager.max_retries = 2
    
    def test_end_to_end_reconnection_flow(self):
        """Test complete reconnection flow from error detection to recovery."""
        # Simulate a browser operation that fails with connection error
        connection_error = InvalidSessionIdException("invalid session id")
        mock_operation = Mock(side_effect=connection_error)
        
        # Execute the operation through connection monitor
        with self.assertRaises(InvalidSessionIdException):
            self.connection_monitor.execute_with_monitoring(mock_operation)
        
        # Verify the complete flow
        # 1. Connection lost status should be sent
        self.mock_ui_callback.assert_any_call("connection_lost", None)
        
        # 2. Reconnecting status should be sent
        self.mock_ui_callback.assert_any_call("reconnecting", None)
        
        # 3. Browser cleanup and reinitialization should occur
        self.mock_browser_manager.cleanup_driver.assert_called()
        self.mock_browser_manager.reinitialize_connection.assert_called()
        
        # 4. Connection state should be updated
        self.assertEqual(self.connection_monitor.get_connection_state(), ConnectionState.CONNECTED)


if __name__ == '__main__':
    unittest.main()