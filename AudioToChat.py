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
from browser import get_chrome_driver, new_chat, load_prompt, browser_communication_thread
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
        
    def submit_topics(self, content):
        logger.info(f"Submitting topics to browser queue: {content[:50]}..." if len(content) > 50 else f"Submitting topics to browser queue: {content}")
        self.browser_queue.put(content)

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
                    thread.join(timeout=5) # Increased timeout for graceful shutdown
                    if thread.is_alive():
                        logger.warning(f"Thread {thread.name} did not terminate after 5 seconds.")
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
        self.topic_processor = TopicProcessor(
            self.root, 
            self.start_listening, 
            self.stop_listening,
            self.submit_topics
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(100, self.process_transcript_queue) # Start UI queue processing
    
    def on_closing(self):
        """Handle window close event."""
        logger.info("Window closing event triggered. Initiating shutdown...")
        self.handle_exit() # Perform cleanup
        
        # Ensure root window is destroyed if it still exists
        if self.root and self.root.winfo_exists():
            try:
                self.root.destroy()
                logger.info("Tkinter root window destroyed.")
            except tk.TclError as e:
                logger.warning(f"Error destroying Tkinter root window (possibly already destroyed): {e}")
        logger.info("Application will now exit.")


    def initialize_audio(self):
        try:
            self.audio = pyaudio.PyAudio()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize PyAudio: {e}")
            return False

    def initialize_browser(self):
        try:
            driver = get_chrome_driver()
            if not driver:
                logger.error("Failed to initialize Chrome driver")
                return False
            
            logger.info(f"Chrome session id: {driver.session_id}")
            
            chat_configs_with_prompts = load_prompt(CHATS) # Load all prompts
            
            active_chat_name = CHAT
            active_chat_config_loaded = chat_configs_with_prompts.get(active_chat_name)
            
            if not active_chat_config_loaded:
                logger.error(f"Failed to load chat configuration (with prompts) for {active_chat_name}")
                return False
            
            # new_chat will use the loaded config (which includes prompts) and send initial prompt
            self.chat_config = new_chat(driver, active_chat_name, active_chat_config_loaded)
            if not self.chat_config:
                logger.error(f"Failed to initialize chat '{active_chat_name}' in browser.")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Error initializing browser: {e}", exc_info=True)
            return False

    def start_threads(self):
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
            
        if not self.chat_config:
            logger.error("Chat not configured. Cannot start browser communication thread.")
            return False # Indicate failure

        browser_comm = threading.Thread(
            name="BrowserCommunication",
            target=browser_communication_thread,
            args=(self.browser_queue, self.run_threads_ref, self.chat_config)
        )
        browser_comm.daemon = True
        self.threads.append(browser_comm)
            
        for thread in self.threads:
            thread.start()
            logger.info(f"Started thread: {thread.name}")
            
        logger.info("All threads started")
        return True # Indicate success

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