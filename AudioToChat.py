# AudioToChat.py
import signal
import sys
import threading
import queue
import pyaudio
import torch
import logging
import tkinter as tk
from typing import Dict, List, Any, Optional

from TopicsUI import TopicProcessor, Topic
from audio_handler import recording_thread
from transcription import transcription_thread
from browser import (
    BrowserManager,
    load_single_chat_prompt,
    SUBMISSION_SUCCESS,
    SUBMISSION_FAILED_INPUT_UNAVAILABLE,
    SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED,
    SUBMISSION_NO_CONTENT
)
from config import (
    MIC_INDEX_ME, MIC_INDEX_OTHERS, CHAT, CHATS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("transcription.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Enable TF32 for better performance if available
if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

class AudioToChat:
    def __init__(self):
        # Global state variables
        self.run_threads_ref = {"active": True, "listening": False}
        self.audio = None
        self.topic_processor: Optional[TopicProcessor] = None
        self.browser_manager: Optional[BrowserManager] = None
        self.auto_submit_mode = "Off"
        
        # Queues for inter-thread communication
        self.audio_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        
        self.mic_data = {
            "ME": {"index": MIC_INDEX_ME, "recording": False, "frames": [], "stream": None},
            "OTHERS": {"index": MIC_INDEX_OTHERS, "recording": False, "frames": [], "stream": None}
        }
        
        self.threads = []
        self.chat_config = None
        self.root = None
        
        signal.signal(signal.SIGINT, self.handle_exit_signal)

    def handle_exit_signal(self, sig, frame):
        logger.info("SIGINT received, initiating shutdown...")
        if self.root and self.root.winfo_exists():
            self.root.after(0, self.on_closing_ui_initiated)
        else:
            self.handle_exit()
            sys.exit(0)

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
        
    def submit_topics(self, content_text: str, selected_topic_objects: List[Topic]):
        if self.browser_manager:
            logger.info(f"AudioToChat: Queueing submission for browser - {len(selected_topic_objects)} topics.")
            self.browser_manager.browser_queue.put({
                "content": content_text,
                "topic_objects": selected_topic_objects 
            })
        else:
            logger.error("Cannot submit topics, browser manager not initialized.")

    def add_transcript_to_ui(self, transcript):
        self.ui_queue.put(transcript)
        
    def process_transcript_queue(self):
        try:
            while not self.ui_queue.empty():
                transcript = self.ui_queue.get_nowait()
                if self.topic_processor:
                    self.topic_processor.add_transcript_to_queue(transcript)
                self.ui_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error processing transcript for UI: {e}")
            
        if self.run_threads_ref["active"] and self.root and self.root.winfo_exists():
            self.root.after(100, self.process_transcript_queue)

    def handle_exit(self):
        if not self.run_threads_ref["active"]:
            # Prevent multiple shutdown calls
            logger.info("Shutdown already in progress or completed.")
            return

        logger.info("Shutdown process started. Cleaning up resources...")
        
        # 1. Signal all threads to stop their loops
        self.run_threads_ref["active"] = False
        self.run_threads_ref["listening"] = False # Ensure this is also signaled
        
        # 2. Specifically stop the browser communication thread first.
        #    This is its own managed thread, separate from the list in self.threads.
        if self.browser_manager:
            logger.info("Stopping browser communication...")
            self.browser_manager.stop_communication_thread()

        # 3. Now, wait for the other threads (recorders, transcriber) to finish.
        logger.info("Waiting for audio and transcription threads to terminate...")
        for thread in self.threads:
            if thread.is_alive():
                logger.info(f"Attempting to join thread: {thread.name}")
                thread.join(timeout=5) # 5-second timeout per thread
                if thread.is_alive():
                    logger.warning(f"Thread {thread.name} did not terminate gracefully.")
        
        logger.info("All primary threads joined or timed out.")

        # 4. Clean up global resources like PyAudio
        if self.audio:
            try:
                logger.info("Terminating PyAudio...")
                self.audio.terminate()
                self.audio = None
                logger.info("PyAudio terminated successfully.")
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}", exc_info=True)
        
        logger.info("Application shutdown cleanup finished.")

    def initialize_ui(self):
        self.root = tk.Tk()
        self.topic_processor = TopicProcessor(
            self.root, self, self.start_listening, self.stop_listening, self.submit_topics
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing_ui_initiated)
        self.root.after(100, self.process_transcript_queue)
    
    def on_closing_ui_initiated(self):
        """Handles the UI window closing event."""
        logger.info("UI window closing event triggered. Initiating full application shutdown...")
        self.handle_exit()
        # After handling backend, destroy the UI if it's still there
        if self.root and self.root.winfo_exists():
            self.root.destroy()
            logger.info("Tkinter root window destroyed.")

    def initialize_audio(self):
        try:
            self.audio = pyaudio.PyAudio()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize PyAudio: {e}")
            return False

    def initialize_browser(self) -> bool:
        try:
            if self.topic_processor:
                self.topic_processor.update_browser_status("info", "Status: Connecting to browser...")

            active_chat_name = CHAT
            base_chat_config = CHATS.get(active_chat_name)
            if not base_chat_config:
                logger.error(f"CRITICAL: No configuration for chat '{active_chat_name}'.")
                if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: No config for {active_chat_name}.")
                return False

            loaded_config = load_single_chat_prompt(active_chat_name, base_chat_config)
            if not loaded_config:
                logger.error(f"Failed to load chat configuration for {active_chat_name}")
                if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: Config load error for {active_chat_name}.")
                return False

            self.browser_manager = BrowserManager(loaded_config, self.update_ui_after_submission)
            if not self.browser_manager.start_driver():
                logger.error("Failed to initialize Chrome driver via BrowserManager")
                if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Failed to connect to Chrome.")
                self.browser_manager = None
                return False

            if self.browser_manager.new_chat(force_new_thread_and_init_prompt=False):
                self.chat_config = self.browser_manager.chat_config
                status_message = f"Status: Connected to {active_chat_name}. Ready."
                if self.topic_processor:
                    self.topic_processor.update_browser_status("browser_ready", status_message)
                logger.info(f"Browser initialized successfully for {active_chat_name}.")
                return True
            else:
                logger.error(f"Failed to initialize chat '{active_chat_name}' via BrowserManager.")
                if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: Failed to init {active_chat_name}.")
                self.browser_manager = None
                return False
        except Exception as e:
            logger.error(f"Error initializing browser: {e}", exc_info=True)
            if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Browser initialization error.")
            return False

    def request_new_ai_thread(self, context_text: Optional[str] = None):
        logger.info("AudioToChat: UI triggered 'New Thread'.")

        if not self.browser_manager or not self.browser_manager.driver:
            logger.error("Cannot start new AI thread: Browser/driver not initialized.")
            if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Browser not ready.")
            return

        if self.topic_processor: self.topic_processor.update_browser_status("info", "Status: Initializing new AI thread...")

        active_chat_name = CHAT
        base_chat_config = CHATS.get(active_chat_name)
        loaded_config = load_single_chat_prompt(active_chat_name, base_chat_config)

        if not loaded_config:
            logger.error(f"Could not load config for {active_chat_name} to start new thread.")
            if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: Config error for {active_chat_name}.")
            return

        self.browser_manager.chat_config = loaded_config
        self.browser_manager.chat_config["driver"] = self.browser_manager.driver

        if self.browser_manager.new_chat(context_text=context_text, force_new_thread_and_init_prompt=True):
            self.chat_config = self.browser_manager.chat_config
            logger.info("New AI thread successfully initialized.")
            if self.topic_processor:
                self.topic_processor.update_browser_status("browser_ready", "Status: New AI thread ready.")
        else:
            logger.error("Failed to initialize new AI thread.")
            if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Failed to start new AI thread.")

    def update_ui_after_submission(self, status: str, successfully_submitted_topics: List[Topic]):
        if not self.root or not self.root.winfo_exists() or not self.topic_processor:
            return

        def _update_task():
            if not self.topic_processor: return

            if status == SUBMISSION_SUCCESS:
                # --- Only focus if it was a manual submission ---
                is_manual_submission = bool(successfully_submitted_topics)

                if is_manual_submission:
                    self.topic_processor.clear_successfully_submitted_topics(successfully_submitted_topics)
                    self.topic_processor.clear_full_text_display()
                
                self.topic_processor.update_browser_status("browser_ready", "Status: Topics submitted successfully.")
                
                if is_manual_submission and self.browser_manager:
                    logger.info("Manual submission successful. Attempting to focus browser window.")
                    self.browser_manager.focus_browser_window()
                else:
                    logger.info("Auto-submission successful. Browser window will not be focused.")
            elif status == SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED:
                self.topic_processor.update_browser_status("browser_human_verification", "AI: Verify Human! (Topics NOT Sent)")
            elif status == SUBMISSION_FAILED_INPUT_UNAVAILABLE:
                self.topic_processor.update_browser_status("browser_input_unavailable", "AI: Input Unavail. (Topics NOT Sent)")
            elif status == SUBMISSION_NO_CONTENT:
                 self.topic_processor.update_browser_status("warning", "Status: No content was sent.")
            else:
                self.topic_processor.update_browser_status("error", "Status: Failed to send topics to AI.")
        
        self.root.after(0, _update_task)

    def start_threads(self) -> bool:
        if not self.audio:
            logger.error("PyAudio not initialized. Cannot start recording threads.")
            return False

        for source in ["ME", "OTHERS"]:
            thread = threading.Thread(
                name=f"Recorder{source}",
                target=recording_thread, 
                args=(source, self.mic_data, self.audio_queue, self.audio, self.run_threads_ref)
            )
            thread.daemon = True
            self.threads.append(thread)
            
        transcriber = threading.Thread(
            name="Transcriber",
            target=transcription_thread, 
            args=(self, self.audio_queue, self.run_threads_ref, self.ui_queue)
        )
        transcriber.daemon = True
        self.threads.append(transcriber)
            
        if not self.browser_manager:
            logger.error("Browser manager not initialized. Cannot start browser communication thread.")
            return False

        self.browser_manager.start_communication_thread()
            
        for thread in self.threads:
            thread.start()
            logger.info(f"Started thread: {thread.name}")
            
        logger.info("All essential threads started or confirmed running.")
        return True

    def run(self):
        try:
            self.initialize_ui()
            
            if not self.initialize_audio():
                logger.error("Critical: Failed to initialize audio. Exiting.")
                if self.root: self.on_closing_ui_initiated()
                return
            
            if not self.initialize_browser():
                logger.error("Critical: Failed to initialize browser. Exiting.")
                if self.root: self.on_closing_ui_initiated()
                return
            
            if not self.start_threads():
                logger.error("Critical: Failed to start worker threads. Exiting.")
                if self.root: self.on_closing_ui_initiated()
                return
            
            logger.info("Starting main UI loop")
            if self.root:
                self.root.mainloop()
            
            logger.info("Main UI loop exited.")
            self.handle_exit()

        except Exception as e:
            logger.critical(f"Unhandled exception in application run: {e}", exc_info=True)
            self.handle_exit()
        finally:
            logger.info("Application run method finished.")

def main():
    app = AudioToChat()
    app.run()

if __name__ == "__main__":
    main()
