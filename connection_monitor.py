# connection_monitor.py
import logging
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from selenium.common.exceptions import (
    WebDriverException, 
    InvalidSessionIdException,
    NoSuchWindowException,
    SessionNotCreatedException
)

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    """Represents the current state of the browser connection."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

@dataclass
class ReconnectionAttempt:
    """Tracks details of a reconnection attempt."""
    attempt_number: int
    timestamp: datetime
    success: bool
    error_message: Optional[str] = None
    delay_used: float = 0.0

class ConnectionMonitor:
    """
    Monitors browser operations and detects connection failures.
    Wraps browser operations to provide connection error detection and recovery.
    """
    
    def __init__(self, browser_manager, ui_callback: Callable, reconnection_manager=None):
        self.browser_manager = browser_manager
        self.ui_callback = ui_callback
        self.reconnection_manager = reconnection_manager
        self.connection_state = ConnectionState.CONNECTED
        self.last_error: Optional[Exception] = None
        self.last_reconnection_time: Optional[datetime] = None
        
    def execute_with_monitoring(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Wraps browser operations with connection monitoring.
        
        Args:
            operation: The browser operation to execute
            *args, **kwargs: Arguments to pass to the operation
            
        Returns:
            The result of the operation if successful
            
        Raises:
            Exception: Re-raises non-connection related exceptions
        """
        try:
            result = operation(*args, **kwargs)
            # If we get here, the operation succeeded
            if self.connection_state == ConnectionState.DISCONNECTED:
                logger.info("Connection appears to be restored after successful operation.")
                self._update_connection_state(ConnectionState.CONNECTED)
            return result
            
        except Exception as e:
            if self.is_connection_error(e):
                logger.warning(f"Connection error detected: {e}")
                self.last_error = e
                self._handle_connection_loss()
                # Re-raise the exception so the caller knows the operation failed
                raise
            else:
                # Not a connection error, re-raise as-is
                raise
    
    def is_connection_error(self, exception: Exception) -> bool:
        """
        Determines if an exception indicates a browser connection loss.
        
        Args:
            exception: The exception to analyze
            
        Returns:
            True if the exception indicates connection loss, False otherwise
        """
        # Direct Selenium connection exceptions
        if isinstance(exception, (InvalidSessionIdException, NoSuchWindowException, SessionNotCreatedException)):
            return True
            
        # WebDriverException with specific error messages
        if isinstance(exception, WebDriverException):
            error_message = str(exception).lower()
            connection_error_indicators = [
                "invalid session id",
                "session deleted",
                "browser has closed",
                "not connected to devtools",
                "chrome not reachable",
                "session not created",
                "no such session"
            ]
            
            return any(indicator in error_message for indicator in connection_error_indicators)
        
        # General connection-related errors
        error_message = str(exception).lower()
        if any(indicator in error_message for indicator in [
            "connection refused",
            "connection reset",
            "connection aborted",
            "connection timeout"
        ]):
            return True
            
        return False
    
    def _handle_connection_loss(self):
        """Initiates the recovery process when connection loss is detected."""
        if self.connection_state != ConnectionState.DISCONNECTED:
            logger.info("Connection loss detected, updating state and initiating recovery.")
            self._update_connection_state(ConnectionState.DISCONNECTED)
            
            # Update UI to show connection lost status
            self.ui_callback("connection_lost", None)
            
            # Trigger automatic reconnection if reconnection manager is available
            if self.reconnection_manager:
                logger.info("Triggering automatic reconnection attempt.")
                self.reconnection_manager.attempt_reconnection()
    
    def _update_connection_state(self, new_state: ConnectionState):
        """Updates the connection state and logs the change."""
        if self.connection_state != new_state:
            old_state = self.connection_state
            self.connection_state = new_state
            logger.info(f"Connection state changed: {old_state.value} -> {new_state.value}")
    
    def get_connection_state(self) -> ConnectionState:
        """Returns the current connection state."""
        return self.connection_state
    
    def set_connection_state(self, state: ConnectionState):
        """Allows external components to update the connection state."""
        self._update_connection_state(state)
        # Track when we successfully reconnect
        if state == ConnectionState.CONNECTED and self.connection_state != ConnectionState.CONNECTED:
            self.last_reconnection_time = datetime.now()
    
    def reset_error(self):
        """Clears the last recorded error."""
        self.last_error = None
    
    def get_last_error(self) -> Optional[Exception]:
        """Returns the last connection error that was detected."""
        return self.last_error
    
    def is_in_post_reconnection_period(self, tolerance_seconds: float = 2.0) -> bool:
        """
        Returns True if we're within the post-reconnection stabilization period.
        
        Args:
            tolerance_seconds: How long after reconnection to be tolerant of errors
        """
        if not self.last_reconnection_time:
            return False
        
        time_since_reconnection = (datetime.now() - self.last_reconnection_time).total_seconds()
        return time_since_reconnection < tolerance_seconds