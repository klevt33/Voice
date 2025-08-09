# audio_monitor.py
import logging
import time
import threading
from enum import Enum
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import pyaudio

logger = logging.getLogger(__name__)

class AudioConnectionState(Enum):
    """Represents the current state of the audio connection."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

@dataclass
class AudioReconnectionAttempt:
    """Tracks details of an audio reconnection attempt."""
    attempt_number: int
    timestamp: datetime
    success: bool
    source: str  # "ME" or "OTHERS"
    error_message: Optional[str] = None
    delay_used: float = 0.0

class AudioMonitor:
    """
    Monitors audio operations and detects audio device failures.
    Handles audio device disconnection and reconnection.
    """
    
    def __init__(self, service_manager, ui_controller):
        self.service_manager = service_manager
        self.ui_controller = ui_controller
        self.connection_state = AudioConnectionState.CONNECTED
        self.last_error: Optional[Exception] = None
        self.reconnection_history = []
        self.max_retries = 3
        self.base_delay = 2.0  # Base delay in seconds
        self.is_reconnecting = False
        self._reconnection_lock = threading.Lock()
        
    def is_audio_device_error(self, exception: Exception) -> bool:
        """
        Determines if an exception indicates an audio device failure.
        
        Args:
            exception: The exception to analyze
            
        Returns:
            True if the exception indicates audio device failure, False otherwise
        """
        error_message = str(exception).lower()
        
        # Common PyAudio error codes for device issues
        audio_device_error_indicators = [
            "errno -9999",  # Unanticipated host error
            "errno -9988",  # Stream closed
            "errno -9996",  # Invalid device
            "errno -9997",  # Invalid sample rate
            "errno -9998",  # Invalid number of channels
            "errno -9986",  # Device unavailable
            "stream closed",
            "device unavailable",
            "invalid device",
            "unanticipated host error"
        ]
        
        return any(indicator in error_message for indicator in audio_device_error_indicators)
    
    def handle_audio_error(self, source: str, exception: Exception):
        """
        Handles audio device errors by attempting reconnection.
        
        Args:
            source: The audio source that failed ("ME" or "OTHERS")
            exception: The exception that occurred
        """
        if not self.is_audio_device_error(exception):
            logger.error(f"Non-device audio error on {source}: {exception}")
            return
        
        logger.warning(f"Audio device error detected on {source}: {exception}")
        self.last_error = exception
        self._update_connection_state(AudioConnectionState.DISCONNECTED)
        
        # Attempt reconnection for this specific source
        self._attempt_audio_reconnection(source)
    
    def _update_connection_state(self, new_state: AudioConnectionState):
        """Updates the connection state and logs the change."""
        if self.connection_state != new_state:
            old_state = self.connection_state
            self.connection_state = new_state
            logger.info(f"Audio connection state changed: {old_state.value} -> {new_state.value}")
    
    def _attempt_audio_reconnection(self, source: str):
        """
        Attempts to reconnect the audio device for a specific source.
        
        Args:
            source: The audio source to reconnect ("ME" or "OTHERS")
        """
        with self._reconnection_lock:
            if self.is_reconnecting:
                logger.info(f"Audio reconnection already in progress for {source}, skipping.")
                return
                
            self.is_reconnecting = True
        
        try:
            logger.info(f"Starting audio reconnection process for {source}...")
            self._update_connection_state(AudioConnectionState.RECONNECTING)
            
            # Update UI to show reconnecting status
            self.ui_controller.update_browser_status("warning", f"Status: Audio device {source} reconnecting...")
            
            success = self._reconnect_audio_source_with_backoff(source)
            
            if success:
                logger.info(f"Audio reconnection successful for {source}!")
                self._update_connection_state(AudioConnectionState.CONNECTED)
                self.ui_controller.update_browser_status("success", f"Status: Audio device {source} reconnected.")
            else:
                logger.error(f"All audio reconnection attempts failed for {source}.")
                self._update_connection_state(AudioConnectionState.FAILED)
                self.ui_controller.update_browser_status("error", f"Status: Audio device {source} connection failed.")
                
        finally:
            self.is_reconnecting = False
    
    def _reconnect_audio_source_with_backoff(self, source: str) -> bool:
        """
        Implements exponential backoff reconnection strategy for audio.
        
        Args:
            source: The audio source to reconnect
            
        Returns:
            True if any reconnection attempt succeeded, False if all failed
        """
        for attempt_num in range(1, self.max_retries + 1):
            logger.info(f"Audio reconnection attempt {attempt_num}/{self.max_retries} for {source}")
            
            attempt_start = datetime.now()
            delay_used = 0.0
            
            try:
                # Calculate delay for this attempt (exponential backoff)
                if attempt_num > 1:
                    delay_used = self.base_delay * (2 ** (attempt_num - 2))
                    logger.info(f"Waiting {delay_used:.1f} seconds before audio reconnection attempt {attempt_num}")
                    time.sleep(delay_used)
                
                # Attempt to reconnect the audio source
                if self._perform_audio_reconnection(source):
                    # Record successful attempt
                    attempt = AudioReconnectionAttempt(
                        attempt_number=attempt_num,
                        timestamp=attempt_start,
                        success=True,
                        source=source,
                        delay_used=delay_used
                    )
                    self.reconnection_history.append(attempt)
                    
                    logger.info(f"Audio reconnection successful for {source} on attempt {attempt_num}")
                    return True
                    
            except Exception as e:
                logger.warning(f"Audio reconnection attempt {attempt_num} failed for {source}: {e}")
                
                # Record failed attempt
                attempt = AudioReconnectionAttempt(
                    attempt_number=attempt_num,
                    timestamp=attempt_start,
                    success=False,
                    source=source,
                    error_message=str(e),
                    delay_used=delay_used
                )
                self.reconnection_history.append(attempt)
        
        logger.error(f"All {self.max_retries} audio reconnection attempts failed for {source}.")
        return False
    
    def _perform_audio_reconnection(self, source: str) -> bool:
        """
        Performs a single audio reconnection attempt for a specific source.
        
        Args:
            source: The audio source to reconnect
            
        Returns:
            True if reconnection succeeded, False otherwise
        """
        try:
            logger.info(f"Attempting to reinitialize audio for {source}...")
            
            # Step 1: Clean up existing stream for this source
            if source in self.service_manager.mic_data:
                mic_info = self.service_manager.mic_data[source]
                if mic_info.get("stream"):
                    try:
                        stream = mic_info["stream"]
                        if stream.is_active():
                            stream.stop_stream()
                        stream.close()
                        logger.info(f"Closed existing audio stream for {source}")
                    except Exception as e:
                        logger.warning(f"Error closing existing stream for {source}: {e}")
                    finally:
                        mic_info["stream"] = None
            
            # Step 2: Reinitialize PyAudio if needed
            if not self.service_manager.audio:
                logger.info("Reinitializing PyAudio...")
                self.service_manager.audio = pyaudio.PyAudio()
            
            # Step 3: Test the specific microphone device
            mic_index = self.service_manager.mic_data[source]["index"]
            try:
                device_info = self.service_manager.audio.get_device_info_by_index(mic_index)
                logger.info(f"Testing {source} microphone: {device_info['name']} (index {mic_index})")
            except Exception as e:
                logger.error(f"Cannot access {source} microphone with index {mic_index}: {e}")
                return False
            
            # Step 4: Create a test stream to verify the device works
            try:
                from config import FORMAT, CHANNELS, SAMPLE_RATE, CHUNK_SIZE
                test_stream = self.service_manager.audio.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    input_device_index=mic_index,
                    frames_per_buffer=CHUNK_SIZE
                )
                
                # Test reading a small amount of data
                test_data = test_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                
                # Close the test stream
                test_stream.close()
                
                logger.info(f"Audio device test successful for {source}")
                
                # Step 5: The recording thread will automatically create a new stream
                # when it detects the device is working again
                logger.info(f"Audio reconnection completed for {source}")
                return True
                
            except Exception as e:
                logger.error(f"Audio device test failed for {source}: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Error during audio reconnection for {source}: {e}")
            return False
    
    def get_connection_state(self) -> AudioConnectionState:
        """Returns the current audio connection state."""
        return self.connection_state
    
    def get_reconnection_history(self) -> list:
        """Returns the history of audio reconnection attempts."""
        return self.reconnection_history.copy()
    
    def clear_reconnection_history(self):
        """Clears the audio reconnection history."""
        self.reconnection_history.clear()
    
    def is_reconnection_in_progress(self) -> bool:
        """Returns True if an audio reconnection is currently in progress."""
        return self.is_reconnecting