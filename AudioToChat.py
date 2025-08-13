# AudioToChat.py
import signal
import sys
import threading
import queue
import torch
import logging
import tkinter as tk
import os
from datetime import datetime, date
from typing import List, Optional

from TopicsUI import UIController, Topic
from managers import StateManager, ServiceManager
from topic_router import TopicRouter
from browser import SUBMISSION_SUCCESS, SUBMISSION_FAILED_INPUT_UNAVAILABLE, SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED, SUBMISSION_NO_CONTENT

def setup_log_rotation(log_file_path: str = "transcription.log"):
    """
    Clear the log file if it's older than today to keep only 1 day of logs.
    """
    try:
        if os.path.exists(log_file_path):
            # Get file modification time
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(log_file_path)).date()
            today = date.today()
            
            # Clear the file if it's older than today
            if file_mod_time < today:
                with open(log_file_path, 'w') as f:
                    f.write("")  # Clear the file
                print(f"Log file {log_file_path} cleared (was from {file_mod_time}, today is {today})")
            else:
                print(f"Log file {log_file_path} is current (from {file_mod_time})")
    except Exception as e:
        print(f"Warning: Could not check/clear log file {log_file_path}: {e}")

# Setup log rotation before configuring logging
setup_log_rotation("transcription.log")

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
    """
    Orchestrates the entire application, connecting the UI, state, services, and topic routing.
    """
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Audio Transcription Processor")
        self.root.geometry("900x650")

        # Queues for inter-thread communication
        self.audio_queue = queue.Queue()
        self.transcribed_topics_queue = queue.Queue()

        # Core components
        self.state_manager = StateManager()
        self.ui_controller = UIController(self.root, self)
        self.service_manager = ServiceManager(self.state_manager, self.ui_controller)
        self.topic_router = TopicRouter(self.state_manager, self.service_manager, self.ui_controller)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing_ui_initiated)
        signal.signal(signal.SIGINT, self.handle_exit_signal)

    def run(self):
        """Initializes services and starts the main application loop."""
        try:
            if not self.service_manager.initialize_audio():
                logger.error("Critical: Failed to initialize audio. Exiting.")
                self.shutdown()
                return

            if not self.service_manager.initialize_browser(self.update_ui_after_submission):
                logger.error("Critical: Failed to initialize browser. Exiting.")
                self.shutdown()
                return

            if not self.service_manager.start_services(self.audio_queue, self.transcribed_topics_queue):
                logger.error("Critical: Failed to start worker threads. Exiting.")
                self.shutdown()
                return

            # Start the topic processing thread
            topic_thread = threading.Thread(target=self.topic_processing_loop, daemon=True)
            topic_thread.start()

            logger.info("Starting main UI loop")
            self.root.mainloop()

        except Exception as e:
            logger.critical(f"Unhandled exception in application run: {e}", exc_info=True)
        finally:
            self.shutdown()

    def topic_processing_loop(self):
        """Continuously checks for transcribed topics and routes them."""
        while self.state_manager.is_active():
            try:
                topic = self.transcribed_topics_queue.get(timeout=1)
                self.topic_router.route_topic(topic)
                self.transcribed_topics_queue.task_done()
            except queue.Empty:
                continue

    def shutdown(self):
        if not self.state_manager.is_active():
            logger.info("Shutdown already in progress.")
            return

        logger.info("Shutdown process started.")
        self.state_manager.shutdown()
        self.service_manager.shutdown_services()

        if self.root and self.root.winfo_exists():
            self.root.destroy()
            logger.info("Tkinter root window destroyed.")
        logger.info("Application shutdown complete.")

    def handle_exit_signal(self, sig, frame):
        logger.info("SIGINT received, initiating shutdown...")
        self.on_closing_ui_initiated()

    def on_closing_ui_initiated(self):
        logger.info("UI window closing event triggered.")
        self.shutdown()

    # --- Callbacks for UIController ---
    def start_listening(self):
        self.state_manager.start_listening()

    def stop_listening(self):
        self.state_manager.stop_listening()

    def set_auto_submit_mode(self, mode: str):
        self.state_manager.set_auto_submit_mode(mode)

    def submit_topics(self, content_text: str, selected_topic_objects: List[Topic]):
        if self.service_manager.browser_manager:
            logger.info(f"Queueing submission for browser - {len(selected_topic_objects)} topics.")
            self.service_manager.browser_manager.browser_queue.put({
                "content": content_text,
                "topic_objects": selected_topic_objects 
            })
        else:
            logger.error("Cannot submit topics, browser manager not initialized.")

    def request_new_ai_thread(self, context_text: Optional[str] = None):
        if self.service_manager.browser_manager:
            self.service_manager.browser_manager.new_chat(context_text, force_new_thread_and_init_prompt=True)

    def request_manual_reconnection(self):
        """Handle manual reconnection request from UI."""
        if self.service_manager.browser_manager and self.service_manager.browser_manager.reconnection_manager:
            # Run reconnection in a separate thread to avoid blocking UI
            def _reconnect():
                try:
                    success = self.service_manager.browser_manager.reconnection_manager.attempt_reconnection()
                    
                    # Dropdown automatically resets, no need to re-enable
                    
                except Exception as e:
                    logger.error(f"Error during manual reconnection: {e}")
                    # Dropdown automatically resets, no need to re-enable
            
            import threading
            reconnect_thread = threading.Thread(target=_reconnect, daemon=True)
            reconnect_thread.start()
        else:
            logger.error("Cannot perform manual reconnection: browser manager or reconnection manager not available.")

    def request_manual_audio_reconnection(self):
        """Handle manual audio reconnection request from UI."""
        if self.service_manager.audio_monitor:
            # Run audio reconnection in a separate thread to avoid blocking UI
            def _audio_reconnect():
                try:
                    logger.info("Manual audio reconnection requested")
                    
                    # Check if listening is currently active and turn it off if needed
                    was_listening = self.state_manager.is_listening()
                    if was_listening:
                        logger.info("Turning off listening mode for audio reconnection")
                        self.state_manager.stop_listening()
                        # Update UI toggle to reflect the state change
                        self.ui_controller.set_listening_state(False)
                        # Give threads a moment to stop listening
                        time.sleep(0.5)
                    
                    # Update UI to show that we're refreshing the microphone list
                    self.ui_controller.update_browser_status("info", "Status: Refreshing microphone list...")
                    
                    # Attempt reconnection for both audio sources together
                    success = self.service_manager.audio_monitor.reconnect_all_audio_sources()
                    
                    if success and was_listening:
                        # Restart listening if it was on before
                        logger.info("Restarting listening mode after successful audio reconnection")
                        time.sleep(0.5)  # Give a moment for reconnection to settle
                        self.state_manager.start_listening()
                        # Update UI toggle to reflect the state change
                        self.ui_controller.set_listening_state(True)
                    
                except Exception as e:
                    logger.error(f"Error during manual audio reconnection: {e}")
                    self.ui_controller.update_browser_status("error", f"Status: Audio reconnection error - {str(e)}")
            
            import threading
            import time
            audio_reconnect_thread = threading.Thread(target=_audio_reconnect, daemon=True)
            audio_reconnect_thread.start()
        else:
            logger.error("Cannot perform manual audio reconnection: audio monitor not available.")
            self.ui_controller.update_browser_status("error", "Status: Audio monitor not available")

    def update_ui_after_submission(self, status: str, submitted_topics: List[Topic]):
        if not self.root or not self.root.winfo_exists():
            return

        def _update_task():
            if status == SUBMISSION_SUCCESS:
                is_manual_submission = bool(submitted_topics)
                if is_manual_submission:
                    self.ui_controller.clear_successfully_submitted_topics(submitted_topics)
                    self.ui_controller.clear_full_text_display()
                self.ui_controller.update_browser_status("browser_ready", "Status: Topics submitted successfully.")
                if is_manual_submission and self.service_manager.browser_manager:
                    self.service_manager.browser_manager.focus_browser_window()
            elif status == SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED:
                self.ui_controller.update_browser_status("browser_human_verification", "AI: Verify Human! (Topics NOT Sent)")
            elif status == SUBMISSION_FAILED_INPUT_UNAVAILABLE:
                self.ui_controller.update_browser_status("browser_input_unavailable", "AI: Input Unavail. (Topics NOT Sent)")
            elif status == SUBMISSION_NO_CONTENT:
                 self.ui_controller.update_browser_status("warning", "Status: No content was sent.")
            elif status == "connection_lost":
                self.ui_controller.update_browser_status("connection_lost")
            elif status == "reconnecting":
                self.ui_controller.update_browser_status("reconnecting")
            elif status == "reconnected":
                self.ui_controller.update_browser_status("reconnected")
            elif status == "connection_failed":
                self.ui_controller.update_browser_status("connection_failed")
            else:
                self.ui_controller.update_browser_status("error", "Status: Failed to send topics to AI.")
        
        self.root.after(0, _update_task)

def main():
    app = AudioToChat()
    app.run()

if __name__ == "__main__":
    main()