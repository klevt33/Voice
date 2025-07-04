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

from TopicsUI import TopicProcessor, Topic # Assuming Topic is used, if not remove
from audio_handler import recording_thread
from transcription import transcription_thread
from browser import (
    get_chrome_driver, new_chat, load_prompt, browser_communication_thread,
    focus_browser_window, # New import
    SUBMISSION_SUCCESS, SUBMISSION_FAILED_INPUT_UNAVAILABLE, # New imports
    SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED, SUBMISSION_NO_CONTENT # New imports
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
        
        # Queues for inter-thread communication
        self.audio_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.browser_queue = queue.Queue()
        
        self.mic_data = {
            "ME": {
                "index": MIC_INDEX_ME,
                "recording": False,
                "frames": [],
                "stream": None
            },
            "OTHERS": {
                "index": MIC_INDEX_OTHERS,
                "recording": False,
                "frames": [],
                "stream": None
            }
        }
        
        self.threads = []
        self.chat_config = None
        self.root = None # Initialize root Tk object
        
        signal.signal(signal.SIGINT, self.handle_exit_signal)

    def handle_exit_signal(self, sig, frame):
        """Handle Ctrl+C signal specifically."""
        logger.info("SIGINT received, initiating shutdown...")
        # Schedule the call to handle_exit in the main thread if Tkinter is running
        if self.root and self.root.winfo_exists():
            self.root.after(0, self.on_closing) # Use on_closing as it handles root.destroy
        else:
            self.handle_exit() # If no UI, call directly
            sys.exit(0) # Exit after cleanup if no UI loop to break

    def start_listening(self):
        logger.info("Starting microphone listening")
        self.run_threads_ref["listening"] = True
        
    def stop_listening(self):
        logger.info("Stopping microphone listening")
        self.run_threads_ref["listening"] = False
        
    def submit_topics(self, content_text: str, selected_topic_objects: List[Topic]):
        logger.info(f"AudioToChat: Queueing submission for browser - {len(selected_topic_objects)} topics.")
        self.browser_queue.put({
            "content": content_text,
            "topic_objects": selected_topic_objects 
        })

    def add_transcript_to_ui(self, transcript):
        self.ui_queue.put(transcript)
        
    def process_transcript_queue(self):
        try:
            while not self.ui_queue.empty():
                transcript = self.ui_queue.get_nowait()
                if self.topic_processor: # Ensure topic_processor exists
                    self.topic_processor.add_transcript_to_queue(transcript)
                self.ui_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error processing transcript for UI: {e}")
            
        if self.run_threads_ref["active"] and self.root and self.root.winfo_exists():
            self.root.after(100, self.process_transcript_queue)

    def handle_exit(self):
        """Handle application cleanup. Should be called by on_closing or SIGINT handler."""
        if not self.run_threads_ref["active"]: # Prevent double execution
            logger.info("Shutdown already in progress or completed.")
            return

        logger.info("Shutdown process started. Cleaning up resources...")
        
        # 1. Signal all threads to stop their work
        self.run_threads_ref["active"] = False
        self.run_threads_ref["listening"] = False # Ensure listening stops if it was on
        
        # 2. Wait for all threads to complete their current tasks and exit
        logger.info("Waiting for threads to terminate...")
        active_threads_before_join = [t for t in self.threads if t.is_alive()]
        if active_threads_before_join:
            logger.info(f"Threads still active before join: {[t.name for t in active_threads_before_join]}")
        
        for thread in self.threads:
            if thread.is_alive():
                try:
                    logger.info(f"Attempting to join thread: {thread.name}")
                    thread.join(timeout=10) # Increased timeout for graceful shutdown
                    if thread.is_alive():
                        logger.warning(f"Thread {thread.name} did not terminate after 10 seconds.")
                    else:
                        logger.info(f"Thread {thread.name} joined successfully.")
                except Exception as e:
                    logger.error(f"Error joining thread {thread.name}: {e}")
            else:
                logger.info(f"Thread {thread.name} was already finished.")
        
        # 3. Threads should have cleaned up their specific resources (like streams).
        # PyAudio termination is the main global audio resource cleanup.
        logger.info("All threads joined or timed out.")

        # As a final check, streams associated with mic_data can be logged if they appear unclosed.
        # However, direct manipulation here is risky if threads didn't exit cleanly.
        for source, data in self.mic_data.items():
            if data["stream"] is not None:
                # This is more for logging state; direct close here can be problematic
                # if the thread managing it is stuck.
                logger.info(f"Post-thread join: Mic {source} stream object exists.")


        # 4. Terminate PyAudio system (must be done after all audio stream operations are finished)
        if self.audio:
            try:
                logger.info("Terminating PyAudio...")
                self.audio.terminate()
                self.audio = None # Mark as terminated
                logger.info("PyAudio terminated successfully.")
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}", exc_info=True)
        
        logger.info("Application shutdown cleanup finished.")

    def initialize_ui(self):
        self.root = tk.Tk()
        # Pass `self` (the AudioToChat instance) as app_controller to TopicProcessor
        self.topic_processor = TopicProcessor(
            self.root,
            self, # Pass self as app_controller
            self.start_listening, 
            self.stop_listening,
            self.submit_topics
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing_ui_initiated) # Changed to new handler name
        self.root.after(100, self.process_transcript_queue)
    
    def on_closing_ui_initiated(self):
        """Handle window close event initiated from UI's WM_DELETE_WINDOW."""
        logger.info("UI window closing event triggered. Initiating full application shutdown...")
        # self.handle_exit() will be called, which should stop threads and then UI can be destroyed.
        # If handle_exit doesn't destroy the root, it should be done after handle_exit.
        
        # Schedule handle_exit to run, then destroy root.
        # This allows handle_exit to complete thread joins before Tkinter vanishes.
        self.handle_exit() # Perform all backend cleanup

        if self.root and self.root.winfo_exists():
            try:
                self.root.destroy()
                logger.info("Tkinter root window destroyed after backend cleanup.")
            except tk.TclError as e:
                logger.warning(f"Error destroying Tkinter root window (possibly already destroyed): {e}")
        logger.info("Application shutdown sequence from UI complete.")

    # def on_closing(self):
    #     """Handle window close event."""
    #     logger.info("Window closing event triggered. Initiating shutdown...")
    #     self.handle_exit() # Perform cleanup
        
    #     # Ensure root window is destroyed if it still exists
    #     if self.root and self.root.winfo_exists():
    #         try:
    #             self.root.destroy()
    #             logger.info("Tkinter root window destroyed.")
    #         except tk.TclError as e:
    #             logger.warning(f"Error destroying Tkinter root window (possibly already destroyed): {e}")
    #     logger.info("Application will now exit.")


    def initialize_audio(self):
        try:
            self.audio = pyaudio.PyAudio()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize PyAudio: {e}")
            return False

    def initialize_browser(self) -> bool:
        try:
            # ... (UI status updates, get_chrome_driver, load_prompt as before) ...
            if self.topic_processor:
                self.topic_processor.update_browser_status("info", "Status: Connecting to browser...")
            
            driver = get_chrome_driver()
            if not driver: # ... (handle driver failure) ...
                logger.error("Failed to initialize Chrome driver")
                if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Failed to connect to Chrome.")
                return False

            logger.info(f"Chrome session id: {driver.session_id}")
            
            chat_configs_with_prompts = load_prompt(CHATS)
            active_chat_name = CHAT
            active_chat_config_loaded = chat_configs_with_prompts.get(active_chat_name)
            
            if not active_chat_config_loaded: # ... (handle config load failure) ...
                logger.error(f"Failed to load chat configuration (with prompts) for {active_chat_name}")
                if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: Config load error for {active_chat_name}.")
                return False

            # --- MODIFICATION: Call new_chat with force_new_thread_and_init_prompt=False ---
            # No context is passed from UI at initial startup.
            if new_chat(driver, active_chat_name, active_chat_config_loaded, context_text=None, force_new_thread_and_init_prompt=False):
                self.chat_config = active_chat_config_loaded
                # Adjust UI message to reflect that we might just be connecting to an existing session
                status_message = f"Status: Connected to {active_chat_name}."
                if not active_chat_config_loaded.get('initial_prompt_sent_this_session', False): # A way to check if prompt was sent by new_chat
                     current_url = driver.current_url
                     if CHATS[active_chat_name]["url"].rstrip('/') in current_url: # If on base URL after potential nav
                        status_message += " Initial prompt sent."
                     else:
                        status_message += " Ready. Use 'New Thread' to start conversation."

                if self.topic_processor:
                    self.topic_processor.update_browser_status("browser_ready", status_message)
                logger.info(f"Browser initialized successfully for {active_chat_name}. Startup connection logic complete.")
                return True
            else:
                # ... (handle new_chat failure as before) ...
                self.chat_config = None 
                logger.error(f"Failed to initialize/connect to chat '{active_chat_name}' in browser via new_chat during startup.")
                if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: Failed to init/connect {active_chat_name}.")
                if driver: 
                    try: 
                        driver.quit() 
                    except Exception as e_q: logger.error(f"Error quitting driver: {e_q}")
                return False
        # ... (outer exception handling as before) ...
        except Exception as e:
            logger.error(f"Error initializing browser: {e}", exc_info=True)
            if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Browser initialization error.")
            return False

    def request_new_ai_thread(self, context_text: Optional[str] = None):
        logger.info(f"AudioToChat: UI triggered 'New Thread'. Context provided: {'Yes' if context_text else 'No'}")
        # ... (checks for self.chat_config, driver as before) ...
        if not self.chat_config or not self.chat_config.get("driver"):
            logger.error("Cannot start new AI thread from UI: Browser/driver not initialized.")
            if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Browser not ready for new thread.")
            return

        if self.topic_processor: self.topic_processor.update_browser_status("info", "Status: Initializing new AI thread...")

        driver = self.chat_config.get("driver")
        active_chat_name = CHAT
        chat_configs_with_prompts = load_prompt(CHATS)
        loaded_config_for_new_chat = chat_configs_with_prompts.get(active_chat_name)

        if not loaded_config_for_new_chat: # ... (handle config load failure) ...
            logger.error(f"Could not load config with prompts for {active_chat_name} to start new thread from UI.")
            if self.topic_processor: self.topic_processor.update_browser_status("error", f"Status: Config error for new thread ({active_chat_name}).")
            return

        # --- MODIFICATION: Call new_chat with force_new_thread_and_init_prompt=True ---
        if new_chat(driver, active_chat_name, loaded_config_for_new_chat, context_text=context_text, force_new_thread_and_init_prompt=True):
            self.chat_config = loaded_config_for_new_chat
            logger.info("New AI thread successfully initialized via UI request.")
            if self.topic_processor:
                self.topic_processor.update_browser_status("browser_ready", "Status: New AI thread ready.")
        else:
            # ... (handle new_chat failure as before) ...
            logger.error("Failed to initialize new AI thread via UI request.")
            if self.topic_processor: self.topic_processor.update_browser_status("error", "Status: Failed to start new AI thread.")

    def update_ui_after_submission(self, status: str, successfully_submitted_topics: List[Topic]):
        """
        Callback to update UI based on submission status from browser thread.
        This method is called from the browser_communication_thread, so UI updates
        must be scheduled to run in the main Tkinter thread using root.after().
        """
        if not self.root or not self.root.winfo_exists() or not self.topic_processor:
            logger.warning("UI not available for update_ui_after_submission.")
            return

        def _update_task():
            if not self.topic_processor: return

            if status == SUBMISSION_SUCCESS:
                if successfully_submitted_topics: # Should always be true if SUCCESS
                    self.topic_processor.clear_successfully_submitted_topics(successfully_submitted_topics)
                    self.topic_processor.clear_full_text_display()
                self.topic_processor.update_browser_status("browser_ready", "Status: Topics submitted successfully.")
                if self.chat_config and self.chat_config.get("driver"): # Focus browser on success
                    focus_browser_window(self.chat_config.get("driver"), self.chat_config)
            elif status == SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED:
                self.topic_processor.update_browser_status("browser_human_verification", "AI: Verify Human! (Topics NOT Sent)")
            elif status == SUBMISSION_FAILED_INPUT_UNAVAILABLE:
                self.topic_processor.update_browser_status("browser_input_unavailable", "AI: Input Unavail. (Topics NOT Sent)")
            elif status == SUBMISSION_NO_CONTENT:
                 self.topic_processor.update_browser_status("warning", "Status: No content was sent.")
            else: # SUBMISSION_FAILED_OTHER or any other failure
                self.topic_processor.update_browser_status("error", "Status: Failed to send topics to AI.")
        
        self.root.after(0, _update_task)

    def start_threads(self) -> bool:
        # Ensure audio system is initialized before starting audio threads
        if not self.audio:
            logger.error("PyAudio not initialized. Cannot start recording threads.")
            return False # Indicate failure

        recorder_me = threading.Thread(
            name="RecorderMe",
            target=recording_thread, 
            args=("ME", self.mic_data, self.audio_queue, self.audio, self.run_threads_ref)
        )
        recorder_me.daemon = True # Daemon threads will exit when main program exits
        self.threads.append(recorder_me)
            
        recorder_others = threading.Thread(
            name="RecorderOthers",
            target=recording_thread, 
            args=("OTHERS", self.mic_data, self.audio_queue, self.audio, self.run_threads_ref)
        )
        recorder_others.daemon = True
        self.threads.append(recorder_others)
            
        transcriber = threading.Thread(
            name="Transcriber",
            target=transcription_thread, 
            args=(self.audio_queue, self.run_threads_ref, self.ui_queue)
        )
        transcriber.daemon = True
        self.threads.append(transcriber)
            
        if not self.chat_config: # Check if browser/chat was initialized
            logger.error("Chat not configured (self.chat_config is None). Cannot start browser communication thread.")
            return False

        browser_comm = threading.Thread(
            name="BrowserCommunication",
            target=browser_communication_thread,
            args=(self.browser_queue, self.run_threads_ref, self.chat_config, self.update_ui_after_submission) # Pass NEW callback
        )
        browser_comm.daemon = True
        self.threads.append(browser_comm)
            
        for thread in self.threads:
            if not thread.is_alive(): # Only start if not already started (e.g. during a restart logic if any)
                thread.start()
                logger.info(f"Started thread: {thread.name}")
            
        logger.info("All essential threads started or confirmed running.")
        return True

    def run(self):
        try:
            self.initialize_ui() # UI first, so errors can be seen if it fails early
            
            if not self.initialize_audio():
                logger.error("Critical: Failed to initialize audio. Exiting.")
                if self.root: self.on_closing() # Attempt graceful UI shutdown
                return
            
            if not self.initialize_browser():
                logger.error("Critical: Failed to initialize browser. Exiting.")
                if self.root: self.on_closing()
                return
            
            if not self.start_threads():
                logger.error("Critical: Failed to start worker threads. Exiting.")
                if self.root: self.on_closing()
                return
            
            logger.info("Starting main UI loop")
            if self.root:
                self.root.mainloop()
            else:
                logger.error("UI Root not initialized. Cannot start mainloop.")
            
            # After mainloop finishes (window closed), ensure cleanup if not already done
            logger.info("Main UI loop exited.")
            self.handle_exit() # Ensure cleanup if on_closing wasn't fully effective or mainloop exited differently

        except Exception as e:
            logger.critical(f"Unhandled exception in application run: {e}", exc_info=True)
            self.handle_exit() # Attempt cleanup on any major error
        finally:
            logger.info("Application run method finished.")


def main():
    app = AudioToChat()
    app.run()

if __name__ == "__main__":
    main()