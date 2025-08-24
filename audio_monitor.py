# audio_monitor.py
import logging
import time
import threading
from enum import Enum
from typing import Callable, Optional, Dict, Any
from datetime import datetime
import pyaudiowpatch as pyaudio

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
        Refreshes the list of available audio devices and detects current default devices.
        
        Returns:
            True if device refresh succeeded, False otherwise
        """
        try:
            logger.info("Refreshing audio device list...")
            
            if not self.service_manager.audio:
                logger.warning("PyAudio not available for device refresh")
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
            
            # Detect current default devices
            from audio_device_utils import get_default_microphone_info, get_default_speakers_loopback_info, format_device_info
            
            me_device = get_default_microphone_info(self.service_manager.audio)
            if me_device:
                logger.info(f"Current default microphone: {format_device_info(me_device)}")
            else:
                logger.warning("No default microphone found")
            
            others_device = get_default_speakers_loopback_info(self.service_manager.audio)
            if others_device:
                logger.info(f"Current default speakers loopback: {format_device_info(others_device)}")
            else:
                logger.warning("No default speakers loopback found")
            
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing device list: {e}")
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
            
            # Step 1: Mark stream as needing recreation (let recording thread handle cleanup)
            logger.info(f"Marking existing stream for recreation: {source}")
            if source in self.service_manager.mic_data:
                mic_info = self.service_manager.mic_data[source]
                if mic_info.get("stream"):
                    # Don't close stream here - let recording thread handle it safely
                    # Just mark it as needing recreation by clearing the reference
                    logger.info(f"Marking stream for recreation: {source}")
                    mic_info["stream"] = None
            
            # Step 2: Refresh device list (without recreating PyAudio instance)
            logger.info("Refreshing device list...")
            if not self._refresh_microphone_list():
                logger.warning(f"Failed to refresh device list for {source}")
                # Continue anyway - maybe the devices are still accessible
            
            # Step 4: Detect current default device for this source (same as startup logic)
            from audio_device_utils import get_default_microphone_info, get_default_speakers_loopback_info, validate_device_info, format_device_info
            
            if source == "ME":
                device_info = get_default_microphone_info(self.service_manager.audio)
            elif source == "OTHERS":
                device_info = get_default_speakers_loopback_info(self.service_manager.audio)
            else:
                logger.error(f"Unknown audio source: {source}")
                return False
            
            if not validate_device_info(device_info, source):
                if source == "ME":
                    logger.error(f"Failed to detect valid device for {source}")
                    return False
                else:
                    logger.warning(f"OTHERS device not available - disabling {source}")
                    device_info = None
            
            # Step 5: Update device info in mic_data (same as startup)
            self.service_manager.mic_data[source]["device_info"] = device_info
            
            if device_info:
                logger.info(f"Detected device for {source}: {format_device_info(device_info)}")
            else:
                logger.info(f"{source} device disabled")
            
            logger.info(f"Audio reconnection completed for {source}")
            return True
            
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
                    me_device_info = self.service_manager.mic_data["ME"]["device_info"]
                    others_device_info = self.service_manager.mic_data["OTHERS"]["device_info"]
                    
                    if me_device_info:
                        me_name = me_device_info['name']
                        me_short = me_name[:20] + "..." if len(me_name) > 23 else me_name
                    else:
                        me_short = "Unknown"
                    
                    if others_device_info:
                        others_name = others_device_info['name']
                        others_short = others_name[:20] + "..." if len(others_name) > 23 else others_name
                        self.ui_controller.update_browser_status("success", f"Status: Audio reconnected - ME: {me_short}, OTHERS: {others_short}")
                    else:
                        self.ui_controller.update_browser_status("success", f"Status: Audio reconnected - ME: {me_short} (OTHERS disabled)")
                except Exception:
                    self.ui_controller.update_browser_status("success", "Status: Audio devices reconnected successfully.")
            else:
                logger.error("Audio reconnection failed for one or both sources.")
                self._update_connection_state(AudioConnectionState.FAILED)
                
                self.ui_controller.update_browser_status("error", "Status: Audio reconnection failed - Check default microphone and speakers")
            
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
            
            # Step 1: Mark streams as needing recreation (let recording threads handle cleanup)
            logger.info("Marking existing streams for recreation...")
            for source in ["ME", "OTHERS"]:
                if source in self.service_manager.mic_data:
                    mic_info = self.service_manager.mic_data[source]
                    if mic_info.get("stream"):
                        # Don't close streams here - let recording threads handle it safely
                        # Just mark them as needing recreation by clearing the reference
                        logger.info(f"Marking stream for recreation: {source}")
                        mic_info["stream"] = None
            
            # Step 2: Refresh device list (without recreating PyAudio instance)
            logger.info("Refreshing device list...")
            if not self._refresh_microphone_list():
                logger.warning("Failed to refresh device list")
                # Continue anyway - maybe the devices are still accessible
            
            # Step 4: Detect and validate both audio sources (same as startup logic)
            from audio_device_utils import get_default_microphone_info, get_default_speakers_loopback_info, validate_device_info, format_device_info
            
            # Detect ME device (default microphone)
            me_device = get_default_microphone_info(self.service_manager.audio)
            if not validate_device_info(me_device, "ME"):
                logger.error("Combined audio reconnection failed - ME device not available")
                return False
            
            # Detect OTHERS device (default speakers loopback)
            others_device = get_default_speakers_loopback_info(self.service_manager.audio)
            if not validate_device_info(others_device, "OTHERS"):
                logger.warning("OTHERS audio device not available - continuing with ME only")
                others_device = None
            
            # Update device info (same as startup)
            self.service_manager.mic_data["ME"]["device_info"] = me_device
            self.service_manager.mic_data["OTHERS"]["device_info"] = others_device
            
            logger.info(f"ME device detected: {format_device_info(me_device)}")
            if others_device:
                logger.info(f"OTHERS device detected: {format_device_info(others_device)}")
            else:
                logger.info("OTHERS device not available")
            
            logger.info("Combined audio reconnection completed successfully")
            return True
                
        except Exception as e:
            logger.error(f"Error during combined audio reconnection: {e}")
            return False