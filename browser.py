# browser.py
import os
import glob
import logging
import time
import threading
from datetime import datetime
from typing import Dict, Optional, Any, List
import queue
import pygetwindow

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from config import DEBUGGER_ADDRESS, ENABLE_SCREENSHOTS, SCREENSHOT_FOLDER
from chat_page import ChatPage, SUBMISSION_SUCCESS, SUBMISSION_FAILED_INPUT_UNAVAILABLE, SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED, SUBMISSION_FAILED_OTHER

# Configure logger for this module
logger = logging.getLogger(__name__)

# --- Submission Status Constants ---
SUBMISSION_NO_CONTENT = "NO_CONTENT"

class BrowserManager:
    """
    Manages the browser driver, the communication thread, and orchestrates
    high-level browser actions by delegating to a ChatPage instance.
    """
    def __init__(self, chat_config: Dict[str, Any], ui_update_callback: callable):
        self.driver: Optional[webdriver.Chrome] = None
        self.chat_page: Optional[ChatPage] = None
        self.chat_config = chat_config
        self.ui_update_callback = ui_update_callback
        self.browser_queue = queue.Queue()
        self.run_threads_ref = {"active": False}
        self.comm_thread: Optional[threading.Thread] = None

    def start_driver(self) -> bool:
        """Initializes the Chrome WebDriver and the ChatPage handler."""
        try:
            logger.info(f"Connecting to Chrome at {DEBUGGER_ADDRESS}")
            c_options = webdriver.ChromeOptions()
            c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
            self.driver = webdriver.Chrome(options=c_options)
            self.chat_page = ChatPage(self.driver, self.chat_config)
            logger.info(f"Successfully connected to Chrome (session: {self.driver.session_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Chrome: {e}")
            self.driver = None
            self.chat_page = None
            return False

    def new_chat(self, context_text: Optional[str] = None, force_new_thread_and_init_prompt: bool = False) -> bool:
        """
        Initializes or resets the chat page by delegating to the ChatPage object.
        """
        if not self.driver or not self.chat_page:
            logger.error("Cannot initialize chat: Driver or ChatPage not available.")
            return False

        try:
            if not self.chat_page.navigate_to_initial_page():
                return False

            if force_new_thread_and_init_prompt:
                logger.info("Forcing new thread and sending initial prompt.")
                if not self.chat_page.start_new_thread():
                    return False
                
                # Construct and send the initial prompt
                initial_prompt = self.chat_config.get("prompt_initial_content", "")
                if context_text and context_text.strip():
                    initial_prompt = f"{initial_prompt}\n\n[CONTEXT] {context_text.strip()}"
                
                if initial_prompt.strip():
                    if not self.chat_page.submit_message(initial_prompt.strip()):
                        logger.error("Failed to send initial prompt message.")
                        return False
                else:
                    logger.info("No initial prompt content to send.")
            
            self.chat_config["last_screenshot_check"] = datetime.now()
            return True

        except WebDriverException as e_wd:
            logger.error(f"WebDriverException in new_chat: {str(e_wd).splitlines()[0]}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in new_chat: {e}", exc_info=True)
            return False

    def _handle_screenshot_upload(self):
        """Checks for and uploads new screenshots."""
        if not ENABLE_SCREENSHOTS or "last_screenshot_check" not in self.chat_config or not self.chat_page:
            return

        last_check_time = self.chat_config["last_screenshot_check"]
        new_screenshots = self._get_new_screenshots(SCREENSHOT_FOLDER, last_check_time)
        
        if new_screenshots:
            logger.info(f"Found {len(new_screenshots)} new screenshots to upload.")
            if not self.chat_page.upload_screenshots(new_screenshots):
                logger.warning("Failed to upload screenshots.")
        
        self.chat_config["last_screenshot_check"] = datetime.now()

    def _get_new_screenshots(self, screenshot_folder: str, last_check_time: datetime) -> List[str]:
        """Gets a list of new screenshot files since the last check."""
        if not os.path.exists(screenshot_folder): return []
        try:
            image_extensions = ['*.png', '*.jpg', '*.jpeg']
            all_files = []
            for ext in image_extensions:
                all_files.extend(glob.glob(os.path.join(screenshot_folder, ext)))
            
            new_files = [os.path.abspath(f) for f in all_files if os.path.getmtime(f) > last_check_time.timestamp()]
            if new_files: logger.info(f"Found {len(new_files)} new screenshots.")
            return new_files
        except Exception as e:
            logger.error(f"Error checking for new screenshots: {e}")
            return []

    def focus_browser_window(self):
        """Brings the browser window to the foreground."""
        if not self.driver: return
        try:
            title = self.driver.title
            windows = pygetwindow.getWindowsWithTitle(title)
            if windows:
                win = windows[0]
                if win.isMinimized: win.restore()
                win.activate()
                logger.info(f"Window '{title}' activated.")
        except Exception as e:
            logger.error(f"General error focusing browser window: {e}")

    def start_communication_thread(self):
        """Starts the thread that listens for messages from the UI queue."""
        if not self.run_threads_ref["active"]:
            self.run_threads_ref["active"] = True
            self.comm_thread = threading.Thread(
                target=self._browser_communication_loop,
                daemon=True
            )
            self.comm_thread.start()
            logger.info("Browser communication thread started.")

    def stop_communication_thread(self):
        """Signals the browser communication thread to stop."""
        if self.run_threads_ref.get("active", False):
            logger.info("Stopping browser communication thread...")
            self.run_threads_ref["active"] = False
            if self.comm_thread and self.comm_thread.is_alive():
                self.comm_thread.join(timeout=5)
            self.comm_thread = None
            logger.info("Browser communication thread shut down.")

    def _browser_communication_loop(self):
        """
        Main loop for browser interaction. Implements the 'Prime and Submit' logic.
        """
        logger.info("Starting browser communication loop with 'Prime and Submit' logic.")
        while self.run_threads_ref["active"]:
            try:
                # Block until at least one item is in the queue
                first_item = self.browser_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            all_items_in_batch = [first_item]
            
            try:
                if not self.chat_page:
                    raise Exception("ChatPage is not initialized.")

                # 1. Prime the input field to enable the submit button
                logger.info("Work detected. Priming input field with 'Waiting...' ")
                if not self.chat_page.prime_input():
                    logger.error("Could not prime input field. Skipping batch.")
                    self.browser_queue.task_done()
                    continue

                # 2. Wait for the site to be ready for submission
                logger.info("Input primed. Waiting for submit button to become active...")
                is_ready = False
                start_time = time.time()
                while time.time() - start_time < 300: # 5-minute overall timeout
                    if self.chat_page.is_ready_for_input() == SUBMISSION_SUCCESS:
                        is_ready = True
                        break
                    if not self.run_threads_ref["active"]: return
                    time.sleep(0.2) # Small delay to prevent busy-waiting

                if not is_ready:
                    logger.error("Timed out waiting for submit button. Aborting batch.")
                    self.ui_update_callback(SUBMISSION_FAILED_INPUT_UNAVAILABLE, [])
                    for _ in all_items_in_batch: self.browser_queue.task_done()
                    continue

                logger.info("Submit button is now active. Browser is ready.")

                # 3. Drain the queue to get all available items NOW that the browser is ready
                while not self.browser_queue.empty():
                    try:
                        all_items_in_batch.append(self.browser_queue.get_nowait())
                    except queue.Empty:
                        break

                # 4. Handle screenshots
                self._handle_screenshot_upload()

                # 5. Construct final payload and submit
                logger.info(f"Processing a batch of {len(all_items_in_batch)} items.")
                message_prompt = self.chat_config.get("prompt_message_content", "").strip()
                combined_topics_content = "\n".join(item['content'] for item in all_items_in_batch if item.get('content'))
                final_payload = f"{message_prompt}\n\n{combined_topics_content}" if message_prompt else combined_topics_content
                combined_topic_objects = [topic for item in all_items_in_batch for topic in item.get('topic_objects', [])]
                
                if final_payload.strip():
                    if self.chat_page.submit_message(final_payload):
                        self.ui_update_callback(SUBMISSION_SUCCESS, combined_topic_objects)
                    else:
                        self.ui_update_callback(SUBMISSION_FAILED_OTHER, [])
                else:
                    self.ui_update_callback(SUBMISSION_NO_CONTENT, combined_topic_objects)

            except Exception as e:
                logger.error(f"Failed to process and submit batch: {e}", exc_info=True)
                self.ui_update_callback(SUBMISSION_FAILED_OTHER, [])
            finally:
                for _ in all_items_in_batch:
                    self.browser_queue.task_done()

        logger.info("Browser communication loop has exited.")

# Standalone utility function
def load_single_chat_prompt(chat_name: str, chat_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Loads prompt files for a single chat configuration."""
    if not chat_config:
        logger.error(f"No configuration provided for '{chat_name}' to load prompts.")
        return None

    updated_config = chat_config.copy()
    
    for key, config_key in [("prompt_init_file", "prompt_initial_content"), ("prompt_msg_file", "prompt_message_content")]:
        file_path = updated_config.get(key)
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                updated_config[config_key] = content
                logger.info(f"Loaded prompt for {chat_name} from {file_path} ({len(content)} chars)")
            except FileNotFoundError:
                logger.error(f"CRITICAL: Prompt file '{file_path}' not found for {chat_name}.")
                return None
            except Exception as e:
                logger.error(f"Error loading prompt file '{file_path}': {e}")
                return None
            
    return updated_config