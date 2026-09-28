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
from browser import BrowserManager
# Submission status constants live in chat_page since the ChatPage extraction.
from chat_page import SUBMISSION_SUCCESS, SUBMISSION_FAILED_OTHER
from connection_monitor import ConnectionMonitor, ConnectionState
from reconnection_manager import ReconnectionManager
from selenium.common.exceptions import InvalidSessionIdException


def wait_until(predicate, timeout=10.0, interval=0.02):
    """
    Wait for a condition that a worker thread is expected to satisfy.

    ConnectionMonitor performs reconnection on a daemon thread, so assertions
    about the outcome have to wait for that worker rather than race it.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


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
        
        # Give the chat page mocks a *successful* default.
        #
        # The communication loop waits for the submit button with
        # `while time.time() - start_time < 300` (browser.py:386) and no sleep
        # or stop-flag check, so a Mock that never returns SUBMISSION_SUCCESS
        # leaves a daemon thread spinning at 100% CPU for five minutes that
        # tearDown cannot stop.  Defaulting the mock to the ready/success values
        # means any test that enqueues work exits that loop immediately.
        self.mock_chat_page.is_ready_for_input.return_value = SUBMISSION_SUCCESS
        self.mock_chat_page.prime_input.return_value = True
        self.mock_chat_page.submit_message.return_value = True
        
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
        
        # The batch is skipped rather than reported as a submission failure:
        # browser.py:373-378 logs the connection error and `continue`s, leaving
        # the connection_lost status as the single source of truth.  Asserting a
        # SUBMISSION_FAILED_OTHER callback here would contradict that design.
        self.assertFalse(
            [status for status, _ in self.ui_updates if status == SUBMISSION_FAILED_OTHER],
            "Connection loss should not also be reported as a submission failure",
        )
    
    def test_topic_submission_recovery_after_reconnection(self):
        """Test that topic submission works after successful reconnection."""
        
        # First, simulate a connection error
        connection_error = InvalidSessionIdException("Session not found")
        self.mock_chat_page.prime_input.side_effect = connection_error
        
        # Mock successful reconnection
        def mock_reinitialize():
            # Reset the mock to simulate successful reconnection.
            # cleanup_driver() nulls out driver/chat_page (browser.py:494-497),
            # so a real reconnection has to install a fresh ChatPage; without this
            # the communication loop keeps raising "ChatPage is not initialized".
            self.browser_manager.driver = self.mock_driver
            self.browser_manager.chat_page = self.mock_chat_page
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
        
        # Verify connection error was detected.  DISCONNECTED is only a
        # transitional state — the monitor immediately starts reconnection on a
        # worker thread, so assert the loss was reported rather than pinning a
        # specific moment-in-time state value.
        self.assertIn(
            "connection_lost",
            [update[0] for update in self.status_updates],
            "Connection loss should be reported to the status bar",
        )
        self.assertNotEqual(
            self.browser_manager.connection_monitor.get_connection_state(),
            ConnectionState.CONNECTED,
        )
        
        # Wait for the automatic reconnection that the connection monitor kicks
        # off on a worker thread when it detects the error.  Calling
        # attempt_reconnection() here instead would race that worker and return
        # False, because ReconnectionManager rejects concurrent attempts
        # (reconnection_manager.py:35-37).
        wait_until(
            lambda: self.browser_manager.connection_monitor.get_connection_state()
            == ConnectionState.CONNECTED
        )
        
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
    
    def test_requeue_batch_preserves_order(self):
        """A deferred batch goes back to the head, ahead of later items."""
        q = queue.Queue()
        for name in ("Topic 1", "Topic 2"):
            q.put({"content": name})
        # This arrives while the batch above was in flight.
        q.put({"content": "Newer topic"})
        
        stub = Mock()
        stub.browser_queue = q
        BrowserManager._requeue_batch(stub, [{"content": "Topic 3"}])
        
        contents = []
        while not q.empty():
            contents.append(q.get_nowait().get("content"))
        self.assertEqual(
            contents,
            ["Topic 3", "Topic 1", "Topic 2", "Newer topic"],
            "Deferred batch must return to the head in its original order",
        )
    
    def test_requeue_batch_fallback_without_queue_internals(self):
        """The fallback path still preserves order when Queue internals are gone."""
        class MinimalQueue:
            """A stand-in for queue.Queue without .mutex/.queue/.not_empty."""
            def __init__(self):
                self._items = []
            def put(self, item):
                self._items.append(item)
            def get_nowait(self):
                if not self._items:
                    raise queue.Empty
                return self._items.pop(0)
            def qsize(self):
                return len(self._items)
            def task_done(self):
                pass
        
        q = MinimalQueue()
        q.put({"content": "Topic 1"})
        q.put({"content": "Topic 2"})
        
        stub = Mock()
        stub.browser_queue = q
        BrowserManager._requeue_batch(stub, [{"content": "Topic 3"}])
        
        contents = []
        while q.qsize():
            contents.append(q.get_nowait().get("content"))
        self.assertEqual(contents, ["Topic 3", "Topic 1", "Topic 2"])
    
    def test_queue_preservation_during_reconnection(self):
        """Queued topics must survive a reconnect instead of being dropped."""
        
        test_topics = [
            {"content": "Topic 1", "topic_objects": []},
            {"content": "Topic 2", "topic_objects": []},
            {"content": "Topic 3", "topic_objects": []}
        ]
        
        for topic in test_topics:
            self.browser_manager.browser_queue.put(topic)
        
        self.assertEqual(self.browser_manager.browser_queue.qsize(), 3, "Queue should have 3 items")
        
        # Simulate the state during a reconnect: connection down and chat_page
        # torn down by cleanup_driver().
        self.browser_manager.connection_monitor.set_connection_state(ConnectionState.DISCONNECTED)
        self.browser_manager.chat_page = None
        
        # Let the communication loop run several defer cycles.  Every pass must
        # hand the batch back rather than consuming it.
        time.sleep(1.0)
        
        # Nothing may be lost while the connection is down.
        self.assertEqual(
            self.browser_manager.browser_queue.qsize(),
            3,
            "Queued topics must not be consumed while the connection is down",
        )
        
        # Bring the connection back, as a successful reconnection would.
        self.browser_manager.chat_page = self.mock_chat_page
        self.browser_manager.connection_monitor.set_connection_state(ConnectionState.CONNECTED)
        self.browser_manager.test_connection_health = Mock(return_value=True)
        self.browser_manager.focus_browser_window = Mock()
        
        # Wait for the deferred topics to be delivered.
        wait_until(lambda: self.mock_chat_page.submit_message.called)
        
        # All three topics must reach the browser, in their original order.
        payload = self.mock_chat_page.submit_message.call_args[0][0]
        self.assertIn("Topic 1", payload)
        self.assertIn("Topic 2", payload)
        self.assertIn("Topic 3", payload)
        self.assertLess(payload.index("Topic 1"), payload.index("Topic 2"))
        self.assertLess(payload.index("Topic 2"), payload.index("Topic 3"))


if __name__ == '__main__':
    unittest.main()