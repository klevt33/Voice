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
            self.ui_callback("reconnecting", [])
            
            # Attempt reconnection with backoff
            success = self.reconnect_with_backoff()
            
            if success:
                logger.info("Reconnection successful!")
                
                # Update connection monitor state
                if self.browser_manager.connection_monitor:
                    self.browser_manager.connection_monitor.set_connection_state(ConnectionState.CONNECTED)
                    self.browser_manager.connection_monitor.reset_error()
                
                # Only show "reconnected" status if browser is on correct page
                # If not on correct page, the warning status from navigate_to_initial_page should remain
                if hasattr(self.browser_manager, 'on_correct_page') and self.browser_manager.on_correct_page:
                    self.ui_callback("reconnected", [])
                    logger.info("Reconnection completed - browser is on correct page.")
                else:
                    logger.info("Reconnection completed - browser not on correct page.")
                
                return True
            else:
                logger.error("All reconnection attempts failed.")
                
                # Update connection monitor state
                if self.browser_manager.connection_monitor:
                    self.browser_manager.connection_monitor.set_connection_state(ConnectionState.FAILED)
                
                # Update UI to show connection failure
                self.ui_callback("connection_failed", [])
                
                return False
                
        finally:
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
            
            logger.info("Browser state restored successfully.")
            return True
            
        except Exception as e:
            logger.error(f"Error restoring browser state: {e}")
            return False
    
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