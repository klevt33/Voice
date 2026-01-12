# reconnection_manager.py
import logging
import time
import threading
from typing import Callable, Optional
from datetime import datetime

from connection_monitor import ConnectionState, ReconnectionAttempt

logger = logging.getLogger(__name__)

class ReconnectionManager:
    """
    Manages browser reconnection attempts with exponential backoff strategy.
    Handles the full reconnection process including retries and state restoration.
    """
    
    def __init__(self, browser_manager, ui_callback: Callable):
        self.browser_manager = browser_manager
        self.ui_callback = ui_callback
        self.max_retries = 3
        self.base_delay = 1.0  # Base delay in seconds
        self.is_reconnecting = False
        self.reconnection_history = []
        self._reconnection_lock = threading.Lock()
        
    def attempt_reconnection(self) -> bool:
        """
        Manages the full reconnection process with retries.
        
        Returns:
            True if reconnection was successful, False otherwise
        """
        with self._reconnection_lock:
            if self.is_reconnecting:
                logger.info("Reconnection already in progress, skipping duplicate attempt.")
                return False
                
            self.is_reconnecting = True
            
        try:
            logger.info("Starting reconnection process...")
            
            # Update connection monitor state
            if self.browser_manager.connection_monitor:
                self.browser_manager.connection_monitor.set_connection_state(ConnectionState.RECONNECTING)
            
            # Update UI to show reconnecting status
            self.ui_callback("reconnecting", None)
            
            # Attempt reconnection with backoff
            success = self.reconnect_with_backoff()
            
            if success:
                logger.info("Reconnection successful!")
                
                # Update connection monitor state BEFORE calling UI callback
                if self.browser_manager.connection_monitor:
                    self.browser_manager.connection_monitor.set_connection_state(ConnectionState.CONNECTED)
                    self.browser_manager.connection_monitor.reset_error()
                
                # Show reconnected status to indicate topic submission is ready
                # Even if not on correct page, the connection is restored and topic submission should work
                self.ui_callback("reconnected", None)
                
                # Log additional details about page status
                if hasattr(self.browser_manager, 'on_correct_page') and self.browser_manager.on_correct_page:
                    logger.info("Reconnection completed - browser is on correct page and ready for topic submission.")
                else:
                    logger.info("Reconnection completed - browser connection restored (topic submission ready, but may need manual navigation).")
                
                return True
            else:
                logger.error("All reconnection attempts failed.")
                
                # Update connection monitor state
                if self.browser_manager.connection_monitor:
                    self.browser_manager.connection_monitor.set_connection_state(ConnectionState.FAILED)
                
                # Update UI to show connection failure
                self.ui_callback("connection_failed", None)
                
                return False
                
        finally:
            with self._reconnection_lock:
                self.is_reconnecting = False
    
    def reconnect_with_backoff(self) -> bool:
        """
        Implements exponential backoff reconnection strategy.
        
        Returns:
            True if any reconnection attempt succeeded, False if all failed
        """
        for attempt_num in range(1, self.max_retries + 1):
            logger.info(f"Reconnection attempt {attempt_num}/{self.max_retries}")
            
            attempt_start = datetime.now()
            delay_used = 0.0
            
            try:
                # Calculate delay for this attempt (exponential backoff)
                if attempt_num > 1:
                    delay_used = self.base_delay * (2 ** (attempt_num - 2))
                    logger.info(f"Waiting {delay_used:.1f} seconds before attempt {attempt_num}")
                    time.sleep(delay_used)
                
                # Attempt to reconnect
                if self._perform_reconnection():
                    # Record successful attempt
                    attempt = ReconnectionAttempt(
                        attempt_number=attempt_num,
                        timestamp=attempt_start,
                        success=True,
                        delay_used=delay_used
                    )
                    self.reconnection_history.append(attempt)
                    
                    logger.info(f"Reconnection successful on attempt {attempt_num}")
                    return True
                    
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt_num} failed: {e}")
                
                # Record failed attempt
                attempt = ReconnectionAttempt(
                    attempt_number=attempt_num,
                    timestamp=attempt_start,
                    success=False,
                    error_message=str(e),
                    delay_used=delay_used
                )
                self.reconnection_history.append(attempt)
        
        logger.error(f"All {self.max_retries} reconnection attempts failed.")
        return False
    
    def _perform_reconnection(self) -> bool:
        """
        Performs a single reconnection attempt.
        
        Returns:
            True if reconnection succeeded, False otherwise
        """
        try:
            # Step 1: Clean up existing driver connection
            logger.info("Cleaning up existing driver connection...")
            self.browser_manager.cleanup_driver()
            
            # Step 2: Reinitialize the connection
            logger.info("Reinitializing browser connection...")
            if not self.browser_manager.reinitialize_connection():
                logger.warning("Failed to reinitialize browser connection.")
                return False
            
            # Step 3: Restore browser to ready state
            logger.info("Restoring browser state...")
            if not self.restore_browser_state():
                logger.warning("Failed to restore browser state.")
                return False
            
            # Step 4: Test connection health
            logger.info("Testing connection health...")
            if not self.browser_manager.test_connection_health():
                logger.warning("Connection health test failed.")
                return False
            
            # Step 5: Allow brief stabilization time for WebDriver session
            logger.info("Allowing WebDriver session to stabilize...")
            time.sleep(0.5)  # Brief delay to ensure session is fully ready
            
            logger.info("Reconnection completed successfully.")
            return True
            
        except Exception as e:
            logger.error(f"Error during reconnection: {e}")
            return False
    
    def restore_browser_state(self) -> bool:
        """
        Restores browser to ready state after reconnection.
        
        Returns:
            True if state restoration succeeded, False otherwise
        """
        try:
            # Navigate to the chat page and ensure it's ready
            # This will handle showing warnings if not on correct page
            if not self.browser_manager.new_chat():
                logger.error("Failed to initialize chat page after reconnection.")
                return False
            
            # Reset any stuck state in the browser communication loop
            # This ensures topic submission will work after reconnection
            self._reset_communication_state()
            
            logger.info("Browser state restored successfully.")
            return True
            
        except Exception as e:
            logger.error(f"Error restoring browser state: {e}")
            return False
    
    def _reset_communication_state(self):
        """Reset communication state to ensure topic submission works after reconnection."""
        try:
            # The browser communication loop should be able to handle new submissions
            # after reconnection. We don't need to restart the thread, just ensure
            # the queue is ready to process new items.
            
            # Log the current queue state for debugging
            if hasattr(self.browser_manager, 'browser_queue'):
                try:
                    queue_size = self.browser_manager.browser_queue.qsize()
                    if queue_size > 0:
                        logger.info(f"Browser queue has {queue_size} pending items after reconnection.")
                    else:
                        logger.info("Browser queue is empty after reconnection.")
                except (AttributeError, TypeError):
                    logger.debug("Could not check queue size (likely in test environment)")
            
            # Ensure the communication thread is still running
            if (hasattr(self.browser_manager, 'run_threads_ref') and 
                not self.browser_manager.run_threads_ref.get("active", False)):
                logger.warning("Browser communication thread is not active after reconnection.")
                # Restart the communication thread if it's not running
                self.browser_manager.start_communication_thread()
                logger.info("Restarted browser communication thread after reconnection.")
            
            # Add a small test item to the queue to wake up the communication loop
            # This ensures the loop will process any pending items after reconnection
            if hasattr(self.browser_manager, 'browser_queue'):
                try:
                    # Add a minimal wake-up item that will be processed and discarded
                    wake_up_item = {"content": "", "topic_objects": [], "_wake_up": True}
                    self.browser_manager.browser_queue.put(wake_up_item)
                    logger.debug("Added wake-up item to browser queue to resume processing.")
                except Exception as e:
                    logger.debug(f"Could not add wake-up item to queue: {e}")
            
            logger.debug("Communication state reset completed.")
            
        except Exception as e:
            logger.error(f"Error resetting communication state: {e}")
            # Don't fail the reconnection for this, just log the error
    
    def get_reconnection_history(self) -> list:
        """Returns the history of reconnection attempts."""
        return self.reconnection_history.copy()
    
    def clear_reconnection_history(self):
        """Clears the reconnection history."""
        self.reconnection_history.clear()
    
    def is_reconnection_in_progress(self) -> bool:
        """Returns True if a reconnection is currently in progress."""
        return self.is_reconnecting
    
    def set_max_retries(self, max_retries: int):
        """Sets the maximum number of reconnection attempts."""
        if max_retries > 0:
            self.max_retries = max_retries
            logger.info(f"Max reconnection retries set to {max_retries}")
    
    def set_base_delay(self, base_delay: float):
        """Sets the base delay for exponential backoff."""
        if base_delay > 0:
            self.base_delay = base_delay
            logger.info(f"Base reconnection delay set to {base_delay} seconds")