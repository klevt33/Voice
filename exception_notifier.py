# exception_notifier.py
import logging
import threading
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)

class ExceptionSeverity(Enum):
    """Severity levels for exception notifications."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class ExceptionNotification:
    """Data structure for tracking exception notifications."""
    source: str              # Component that reported the exception
    exception: Exception     # Original exception object
    severity: ExceptionSeverity  # Severity level
    user_message: str       # User-friendly message
    timestamp: datetime     # When the exception occurred
    count: int = 1          # Number of similar exceptions
    
    def get_message_hash(self) -> str:
        """Generate a hash for deduplication based on source and message."""
        return f"{self.source}:{self.user_message}"

class ExceptionNotifier:
    """
    Singleton class that manages exception notifications and integrates with the UI status system.
    Provides centralized exception reporting with deduplication and recovery detection.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._active_exceptions: Dict[str, ExceptionNotification] = {}
        self._exception_history: Dict[str, ExceptionNotification] = {}
        self._ui_update_callback: Optional[Callable] = None
        self._cleanup_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        
        # Configuration
        self.DEDUPLICATION_WINDOW = 30  # seconds
        self.TIMEOUT_DURATION = 300     # 5 minutes
        self.MAX_HISTORY_SIZE = 10      # per source
        
        logger.info("ExceptionNotifier initialized")
    
    def set_ui_update_callback(self, callback: Callable[[str, str], None]):
        """
        Set the callback function for updating the UI status.
        
        Args:
            callback: Function that takes (status_key, message) parameters
        """
        self._ui_update_callback = callback
        logger.debug("UI update callback set")
    
    def notify_exception(self, 
                        source: str, 
                        exception: Exception, 
                        severity: str = "error",
                        user_message: str = None) -> None:
        """
        Report an exception to the notification system.
        
        Args:
            source: Component that reported the exception
            exception: The exception object
            severity: Severity level ("error", "warning", "info")
            user_message: User-friendly message (auto-generated if None)
        """
        try:
            # Convert severity string to enum
            try:
                severity_enum = ExceptionSeverity(severity)
            except ValueError:
                logger.warning(f"Invalid severity '{severity}', defaulting to ERROR")
                severity_enum = ExceptionSeverity.ERROR
            
            # Generate user message if not provided
            if user_message is None:
                user_message = self._generate_user_message(source, exception, severity_enum)
            
            # Create notification
            notification = ExceptionNotification(
                source=source,
                exception=exception,
                severity=severity_enum,
                user_message=user_message,
                timestamp=datetime.now()
            )
            
            with self._lock:
                # Check for deduplication
                message_hash = notification.get_message_hash()
                existing = self._active_exceptions.get(message_hash)
                
                if existing and self._should_deduplicate(existing, notification):
                    # Update existing notification
                    existing.count += 1
                    existing.timestamp = notification.timestamp
                    logger.debug(f"Deduplicated exception from {source}, count: {existing.count}")
                else:
                    # New or different exception
                    self._active_exceptions[message_hash] = notification
                    logger.info(f"New exception notification from {source}: {user_message}")
                
                # Update UI
                self._update_ui_status(notification)
                
                # Store in history
                self._add_to_history(source, notification)
                
                # Schedule cleanup
                self._schedule_cleanup()
                
        except Exception as e:
            logger.error(f"Error in exception notification system: {e}")
            # Fallback: try to show a basic error message
            if self._ui_update_callback:
                try:
                    self._ui_update_callback("error", f"Exception in {source}")
                except Exception:
                    pass  # Avoid infinite recursion
    
    def notify_transcription_fallback(self, from_method: str, to_method: str, reason: str = None):
        """
        Notify about transcription fallback activation
        
        Args:
            from_method: Method that failed
            to_method: Method being used as fallback
            reason: Optional reason for fallback
        """
        try:
            message = f"Transcription fallback: {from_method} → {to_method}"
            if reason:
                message += f" ({reason})"
            
            # Create a synthetic exception for the notification system
            fallback_exception = Exception(f"Fallback from {from_method} to {to_method}: {reason or 'Method failed'}")
            
            self.notify_exception(
                source="transcription_fallback",
                exception=fallback_exception,
                severity="warning",
                user_message=message
            )
            
        except Exception as e:
            logger.error(f"Error notifying transcription fallback: {e}")
    
    def clear_exception_status(self, source: str) -> None:
        """
        Clear exception status for a specific source (recovery detected).
        
        Args:
            source: Component source to clear
        """
        try:
            with self._lock:
                # Find and remove exceptions from this source
                to_remove = []
                for message_hash, notification in self._active_exceptions.items():
                    if notification.source == source:
                        to_remove.append(message_hash)
                
                for message_hash in to_remove:
                    del self._active_exceptions[message_hash]
                    logger.info(f"Cleared exception status for {source}")
                
                # If we cleared any exceptions, update UI to normal status
                if to_remove and self._ui_update_callback:
                    # Check if there are any other active exceptions
                    if not self._active_exceptions:
                        # No active exceptions, return to normal status
                        self._ui_update_callback("success", "Status: Ready")
                    else:
                        # Show the most recent remaining exception
                        latest = max(self._active_exceptions.values(), key=lambda x: x.timestamp)
                        self._update_ui_status(latest)
                        
        except Exception as e:
            logger.error(f"Error clearing exception status for {source}: {e}")
    
    def is_exception_active(self, source: str) -> bool:
        """
        Check if there are active exceptions for a specific source.
        
        Args:
            source: Component source to check
            
        Returns:
            True if there are active exceptions for the source
        """
        with self._lock:
            return any(notification.source == source 
                      for notification in self._active_exceptions.values())
    
    def get_active_exceptions(self) -> Dict[str, ExceptionNotification]:
        """Get a copy of currently active exceptions."""
        with self._lock:
            return self._active_exceptions.copy()
    
    def _generate_user_message(self, source: str, exception: Exception, severity: ExceptionSeverity) -> str:
        """Generate a user-friendly message for an exception."""
        exception_str = str(exception).lower()
        
        # CUDA-specific error detection
        if any(keyword in exception_str for keyword in ["cuda", "gpu", "device"]):
            if "out of memory" in exception_str:
                return "CUDA Error - GPU out of memory"
            elif "driver" in exception_str:
                return "CUDA Error - GPU driver issue"
            else:
                return "CUDA Error - Transcription unavailable"
        
        # Audio-specific error detection
        if source.startswith("audio"):
            if "device" in exception_str:
                return "Audio Device Error - Check microphone connection"
            else:
                return "Audio Error - Recording issue detected"
        
        # Transcription errors
        if source == "transcription":
            # Check for API-specific errors
            if "authentication" in exception_str or "api key" in exception_str:
                return "API Authentication Error - Check API key configuration"
            elif "rate limit" in exception_str or "quota" in exception_str:
                return "API Rate Limit Exceeded - Requests throttled"
            elif "network" in exception_str or "connection" in exception_str:
                return "API Network Error - Check internet connection"
            elif "groq" in exception_str or "api" in exception_str:
                return "API Transcription Error - Service unavailable"
            else:
                return "Transcription Error - Speech processing failed"
        
        # Generic error message
        return f"{source.title()} Error - {str(exception)[:50]}..."
    
    def _should_deduplicate(self, existing: ExceptionNotification, new: ExceptionNotification) -> bool:
        """Check if a new exception should be deduplicated with an existing one."""
        time_diff = new.timestamp - existing.timestamp
        return (time_diff.total_seconds() <= self.DEDUPLICATION_WINDOW and
                existing.get_message_hash() == new.get_message_hash())
    
    def _update_ui_status(self, notification: ExceptionNotification):
        """Update the UI status based on the notification."""
        if not self._ui_update_callback:
            return
        
        try:
            # Determine status key based on source and severity
            status_key = self._get_status_key(notification)
            
            # Format message with count if > 1
            message = notification.user_message
            if notification.count > 1:
                message = f"{message} ({notification.count}x)"
            
            self._ui_update_callback(status_key, message)
            
        except Exception as e:
            logger.error(f"Error updating UI status: {e}")
    
    def _get_status_key(self, notification: ExceptionNotification) -> str:
        """Determine the appropriate status key for a notification."""
        source = notification.source
        exception_str = str(notification.exception).lower()
        
        # CUDA errors get special treatment
        if any(keyword in exception_str for keyword in ["cuda", "gpu"]):
            return "cuda_error"
        
        # Audio errors
        if source.startswith("audio"):
            return "audio_error"
        
        # Transcription errors
        if source == "transcription":
            # Check for API-specific error types
            if "authentication" in exception_str or "api key" in exception_str:
                return "api_auth_error"
            elif "rate limit" in exception_str or "quota" in exception_str:
                return "api_rate_limit"
            elif "network" in exception_str or "connection" in exception_str:
                return "api_network_error"
            elif "groq" in exception_str or "api" in exception_str:
                return "api_error"
            else:
                return "transcription_error"
        
        # Transcription fallback notifications
        if source == "transcription_fallback":
            return "transcription_fallback"
        
        # Default based on severity
        if notification.severity == ExceptionSeverity.ERROR:
            return "error"
        elif notification.severity == ExceptionSeverity.WARNING:
            return "warning"
        else:
            return "info"
    
    def _add_to_history(self, source: str, notification: ExceptionNotification):
        """Add notification to history with size limits."""
        history_key = f"{source}_history"
        if history_key not in self._exception_history:
            self._exception_history[history_key] = []
        
        history = self._exception_history[history_key]
        history.append(notification)
        
        # Limit history size
        if len(history) > self.MAX_HISTORY_SIZE:
            history.pop(0)
    
    def _schedule_cleanup(self):
        """Schedule cleanup of old exceptions."""
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        
        self._cleanup_timer = threading.Timer(self.TIMEOUT_DURATION, self._cleanup_old_exceptions)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()
    
    def _cleanup_old_exceptions(self):
        """Remove old exceptions that have timed out."""
        try:
            with self._lock:
                current_time = datetime.now()
                to_remove = []
                
                for message_hash, notification in self._active_exceptions.items():
                    age = current_time - notification.timestamp
                    if age.total_seconds() > self.TIMEOUT_DURATION:
                        to_remove.append(message_hash)
                
                for message_hash in to_remove:
                    del self._active_exceptions[message_hash]
                    logger.info(f"Cleaned up old exception: {message_hash}")
                
                # Update UI if we removed exceptions
                if to_remove:
                    if not self._active_exceptions:
                        # No active exceptions, return to normal
                        if self._ui_update_callback:
                            self._ui_update_callback("success", "Status: Ready")
                    else:
                        # Show most recent remaining exception
                        latest = max(self._active_exceptions.values(), key=lambda x: x.timestamp)
                        self._update_ui_status(latest)
                
        except Exception as e:
            logger.error(f"Error during exception cleanup: {e}")

# Global instance for easy access
exception_notifier = ExceptionNotifier()