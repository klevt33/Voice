# managers.py
import logging
import threading
import pyaudio
from typing import Dict, Any, Optional

from audio_handler import recording_thread
from transcription import transcription_thread
from browser import BrowserManager, load_single_chat_prompt
from config import MIC_INDEX_ME, MIC_INDEX_OTHERS, CHAT, CHATS

logger = logging.getLogger(__name__)

class StateManager:
    """Manages the shared state of the application."""
    def __init__(self):
        self.run_threads_ref = {"active": True, "listening": False}
        self.auto_submit_mode = "Off"

    def is_active(self) -> bool:
        return self.run_threads_ref["active"]

    def is_listening(self) -> bool:
        return self.run_threads_ref["listening"]

    def start_listening(self):
        logger.info("Starting microphone listening")
        self.run_threads_ref["listening"] = True

    def stop_listening(self):
        logger.info("Stopping microphone listening")
        self.run_threads_ref["listening"] = False

    def set_auto_submit_mode(self, mode: str):
        if mode in ["Off", "Others", "All"]:
            self.auto_submit_mode = mode
            logger.info(f"Auto-submit mode set to: {mode}")
        else:
            logger.warning(f"Attempted to set invalid auto-submit mode: {mode}")

    def shutdown(self):
        logger.info("StateManager shutting down.")
        self.run_threads_ref["active"] = False
        self.run_threads_ref["listening"] = False

class ServiceManager:
    """
    Manages the lifecycle of external services like audio and browser automation.
    """
    def __init__(self, state_manager: StateManager, ui_controller):
        self.state_manager = state_manager
        self.ui_controller = ui_controller
        self.audio: Optional[pyaudio.PyAudio] = None
        self.browser_manager: Optional[BrowserManager] = None
        self.threads = []
        self.mic_data = {
            "ME": {"index": MIC_INDEX_ME, "stream": None},
            "OTHERS": {"index": MIC_INDEX_OTHERS, "stream": None}
        }

    def initialize_audio(self) -> bool:
        try:
            self.audio = pyaudio.PyAudio()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize PyAudio: {e}")
            return False

    def initialize_browser(self, ui_update_callback) -> bool:
        try:
            self.ui_controller.update_browser_status("info", "Status: Connecting to browser...")
            active_chat_name = CHAT
            base_chat_config = CHATS.get(active_chat_name)
            if not base_chat_config:
                logger.error(f"CRITICAL: No configuration for chat '{active_chat_name}'.")
                self.ui_controller.update_browser_status("error", f"Status: No config for {active_chat_name}.")
                return False

            loaded_config = load_single_chat_prompt(active_chat_name, base_chat_config)
            if not loaded_config:
                self.ui_controller.update_browser_status("error", f"Status: Config load error for {active_chat_name}.")
                return False

            self.browser_manager = BrowserManager(loaded_config, ui_update_callback)
            if not self.browser_manager.start_driver():
                self.ui_controller.update_browser_status("error", "Status: Failed to connect to Chrome.")
                return False

            if self.browser_manager.new_chat():
                self.ui_controller.update_browser_status("browser_ready", f"Status: Connected to {active_chat_name}. Ready.")
                return True
            else:
                self.ui_controller.update_browser_status("error", f"Status: Failed to init {active_chat_name}.")
                return False
        except Exception as e:
            logger.error(f"Error initializing browser: {e}", exc_info=True)
            self.ui_controller.update_browser_status("error", "Status: Browser initialization error.")
            return False

    def start_services(self, audio_queue, transcribed_topics_queue) -> bool:
        if not self.audio:
            logger.error("PyAudio not initialized. Cannot start services.")
            return False

        for source in ["ME", "OTHERS"]:
            thread = threading.Thread(
                name=f"Recorder{source}",
                target=recording_thread, 
                args=(source, self.mic_data, audio_queue, self.audio, self.state_manager.run_threads_ref)
            )
            thread.daemon = True
            self.threads.append(thread)
            
        transcriber = threading.Thread(
            name="Transcriber",
            target=transcription_thread, 
            args=(audio_queue, transcribed_topics_queue, self.state_manager.run_threads_ref)
        )
        transcriber.daemon = True
        self.threads.append(transcriber)
            
        if self.browser_manager:
            self.browser_manager.start_communication_thread()
            
        for thread in self.threads:
            thread.start()
            logger.info(f"Started thread: {thread.name}")
            
        return True

    def shutdown_services(self):
        logger.info("Shutting down services...")
        if self.browser_manager:
            self.browser_manager.stop_communication_thread()

        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5)

        if self.audio:
            self.audio.terminate()
            logger.info("PyAudio terminated.")
