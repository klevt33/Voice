# audio_monitor.py
import logging
import time
import threading
from enum import Enum
from typing import Callable, Optional, Dict, Any
from datetime import datetime
import pyaudio

logger = logging.getLogger(__name__)

class AudioConnectionState(Enum):
    """Represents the current state of the audio connection."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"



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
        Handles audio device errors by scheduling reconnection in a separate thread.
        This avoids threading conflicts with the recording threads.
        
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
        
        # Schedule reconnection in a separate thread to avoid conflicts with recording threads
        self._schedule_automatic_reconnection(source)
    
    def _update_connection_state(self, new_state: AudioConnectionState):
        """Updates the connection state and logs the change."""
        if self.connection_state != new_state:
            old_state = self.connection_state
            self.connection_state = new_state
            logger.info(f"Audio connection state changed: {old_state.value} -> {new_state.value}")
    
    def _schedule_automatic_reconnection(self, source: str):
        """
        Schedules automatic audio reconnection in a separate thread to avoid threading conflicts.
        This works exactly like manual reconnection but is triggered automatically.
        
        Args:
            source: The audio source that failed ("ME" or "OTHERS")
        """
        def _automatic_reconnect():
            try:
                logger.info(f"Automatic audio reconnection triggered by {source} error")
                
                # Check if listening is currently active and turn it off if needed
                was_listening = self.service_manager.state_manager.is_listening()
                if was_listening:
                    logger.info("Turning off listening mode for automatic audio reconnection")
                    self.service_manager.state_manager.stop_listening()
                    # Give threads a moment to stop listening
                    time.sleep(0.5)
                
                # Update UI to show that we're reconnecting
                self.ui_controller.update_browser_status("warning", "Status: Audio error detected, reconnecting...")
                
                # Attempt reconnection using the same method as manual reconnection
                success = self.reconnect_all_audio_sources()
                
                if success and was_listening:
                    # Restart listening if it was on before
                    logger.info("Restarting listening mode after successful automatic audio reconnection")
                    time.sleep(0.5)  # Give a moment for reconnection to settle
                    self.service_manager.state_manager.start_listening()
                
            except Exception as e:
                logger.error(f"Error during automatic audio reconnection: {e}")
                self.ui_controller.update_browser_status("error", f"Status: Automatic audio reconnection failed - {str(e)}")
        
        # Run in a separate daemon thread to avoid blocking the recording thread
        import threading
        reconnect_thread = threading.Thread(target=_automatic_reconnect, daemon=True)
        reconnect_thread.start()
    

    
    def _refresh_microphone_list(self) -> bool:
        """
        Refreshes the list of available microphones without changing device assignments.
        Simply scans for available devices and logs what's found.
        
        Returns:
            True if microphone refresh succeeded, False otherwise
        """
        try:
            logger.info("Refreshing microphone list...")
            
            if not self.service_manager.audio:
                logger.warning("PyAudio not available for microphone refresh")
                return False
            
            # Get current device count
            device_count = self.service_manager.audio.get_device_count()
            logger.info(f"Found {device_count} total audio devices")
            
            # Count available input devices
            input_device_count = 0
            for i in range(device_count):
                try:
                    device_info = self.service_manager.audio.get_device_info_by_index(i)
                    if device_info['maxInputChannels'] > 0:  # Only input devices
                        input_device_count += 1
                        logger.debug(f"Available input device {i}: {device_info['name']}")
                except Exception as e:
                    logger.warning(f"Error getting info for device {i}: {e}")
            
            logger.info(f"Found {input_device_count} input devices")
            
            # Check what the current microphone indices point to now (but don't change them)
            for source in ["ME", "OTHERS"]:
                current_index = self.service_manager.mic_data[source]["index"]
                
                try:
                    device_info = self.service_manager.audio.get_device_info_by_index(current_index)
                    if device_info['maxInputChannels'] > 0:
                        logger.info(f"{source} microphone index {current_index} now points to: {device_info['name']}")
                    else:
                        logger.warning(f"{source} microphone index {current_index} is not an input device: {device_info['name']}")
                except Exception as e:
                    logger.warning(f"{source} microphone index {current_index} is not accessible: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing microphone list: {e}")
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
            
            # Step 2: Force reinitialize PyAudio to refresh device list
            # This is crucial when devices are plugged/unplugged as device indices can shift
            logger.info("Force reinitializing PyAudio to refresh device list...")
            if self.service_manager.audio:
                try:
                    self.service_manager.audio.terminate()
                    logger.info("Terminated existing PyAudio instance")
                except Exception as e:
                    logger.warning(f"Error terminating existing PyAudio: {e}")
            
            # Create fresh PyAudio instance
            self.service_manager.audio = pyaudio.PyAudio()
            logger.info("Created fresh PyAudio instance")
            
            # Step 3: Refresh microphone list with the new PyAudio instance
            if not self._refresh_microphone_list():
                logger.warning(f"Failed to refresh microphone list for {source}")
                # Continue anyway - maybe the devices are still accessible
            
            # Step 4: Test the specific microphone device with fresh device info
            mic_index = self.service_manager.mic_data[source]["index"]
            try:
                device_info = self.service_manager.audio.get_device_info_by_index(mic_index)
                logger.info(f"Testing {source} microphone: {device_info['name']} (index {mic_index})")
            except Exception as e:
                logger.error(f"Cannot access {source} microphone with index {mic_index}: {e}")
                return False
            
            # Step 5: Create a test stream to verify the device works
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
                
                # Test reading a chunk to ensure the device works
                test_data = test_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                logger.debug(f"Test read successful for {source}")
                
                # Close the test stream
                test_stream.close()
                
                logger.info(f"Audio device test successful for {source}")
                
                # Step 6: The recording thread will automatically create a new stream
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
    

    def is_reconnection_in_progress(self) -> bool:
        """Returns True if an audio reconnection is currently in progress."""
        return self.is_reconnecting
    
    def reconnect_all_audio_sources(self) -> bool:
        """
        Reconnects both ME and OTHERS audio sources together with consolidated status updates.
        
        Returns:
            True if both sources reconnected successfully, False otherwise
        """
        with self._reconnection_lock:
            if self.is_reconnecting:
                logger.info("Audio reconnection already in progress, skipping.")
                return False
                
            self.is_reconnecting = True
        
        try:
            logger.info("Starting audio reconnection process for both ME and OTHERS...")
            self._update_connection_state(AudioConnectionState.RECONNECTING)
            
            # Update UI to show reconnecting status
            self.ui_controller.update_browser_status("warning", "Status: Refreshing microphones and reconnecting audio...")
            
            # Perform the reconnection process once for both sources
            success = self._perform_combined_audio_reconnection()
            
            if success:
                logger.info("Audio reconnection successful for both sources!")
                self._update_connection_state(AudioConnectionState.CONNECTED)
                
                # Get device names for consolidated success message
                try:
                    me_index = self.service_manager.mic_data["ME"]["index"]
                    others_index = self.service_manager.mic_data["OTHERS"]["index"]
                    me_device = self.service_manager.audio.get_device_info_by_index(me_index)['name']
                    others_device = self.service_manager.audio.get_device_info_by_index(others_index)['name']
                    
                    # Truncate device names if too long
                    me_short = me_device[:20] + "..." if len(me_device) > 23 else me_device
                    others_short = others_device[:20] + "..." if len(others_device) > 23 else others_device
                    
                    self.ui_controller.update_browser_status("success", f"Status: Audio reconnected - ME: {me_short}, OTHERS: {others_short}")
                except Exception:
                    self.ui_controller.update_browser_status("success", "Status: Audio devices reconnected successfully.")
            else:
                logger.error("Audio reconnection failed for one or both sources.")
                self._update_connection_state(AudioConnectionState.FAILED)
                
                me_index = self.service_manager.mic_data["ME"]["index"]
                others_index = self.service_manager.mic_data["OTHERS"]["index"]
                self.ui_controller.update_browser_status("error", f"Status: Audio reconnection failed - Check ME (index {me_index}) and OTHERS (index {others_index}) in config.py")
            
            return success
                
        finally:
            self.is_reconnecting = False
    
    def _perform_combined_audio_reconnection(self) -> bool:
        """
        Performs audio reconnection for both sources with a single PyAudio reinitialization.
        
        Returns:
            True if both sources reconnected successfully, False otherwise
        """
        try:
            logger.info("Performing combined audio reconnection...")
            
            # Step 1: Clean up existing streams for both sources
            for source in ["ME", "OTHERS"]:
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
            
            # Step 2: Force reinitialize PyAudio to refresh device list
            logger.info("Force reinitializing PyAudio to refresh device list...")
            if self.service_manager.audio:
                try:
                    self.service_manager.audio.terminate()
                    logger.info("Terminated existing PyAudio instance")
                except Exception as e:
                    logger.warning(f"Error terminating existing PyAudio: {e}")
            
            # Create fresh PyAudio instance
            self.service_manager.audio = pyaudio.PyAudio()
            logger.info("Created fresh PyAudio instance")
            
            # Step 3: Refresh microphone list with the new PyAudio instance
            if not self._refresh_microphone_list():
                logger.warning("Failed to refresh microphone list")
                # Continue anyway - maybe the devices are still accessible
            
            # Step 4: Test both microphone devices
            both_sources_working = True
            
            for source in ["ME", "OTHERS"]:
                mic_index = self.service_manager.mic_data[source]["index"]
                try:
                    device_info = self.service_manager.audio.get_device_info_by_index(mic_index)
                    logger.info(f"Testing {source} microphone: {device_info['name']} (index {mic_index})")
                    
                    # Test the device by creating a stream
                    from config import FORMAT, CHANNELS, SAMPLE_RATE, CHUNK_SIZE
                    test_stream = self.service_manager.audio.open(
                        format=FORMAT,
                        channels=CHANNELS,
                        rate=SAMPLE_RATE,
                        input=True,
                        input_device_index=mic_index,
                        frames_per_buffer=CHUNK_SIZE
                    )
                    
                    # Test reading a chunk
                    test_data = test_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    test_stream.close()
                    
                    logger.info(f"Audio device test successful for {source}")
                    
                except Exception as e:
                    logger.error(f"Audio device test failed for {source}: {e}")
                    both_sources_working = False
            
            if both_sources_working:
                logger.info("Combined audio reconnection completed successfully")
                return True
            else:
                logger.error("Combined audio reconnection failed - one or more devices not working")
                return False
                
        except Exception as e:
            logger.error(f"Error during combined audio reconnection: {e}")
            return False