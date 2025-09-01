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
from connection_monitor import ConnectionMonitor, ConnectionState
from reconnection_manager import ReconnectionManager

# Configure logger for this module
logger = logging.getLogger(__name__)

# --- Submission Status Constants ---
SUBMISSION_NO_CONTENT = "NO_CONTENT"

class BrowserManager:
    """
    Manages the browser driver, the communication thread, and orchestrates
    high-level browser actions by delegating to a ChatPage instance.
    """
    def __init__(self, chat_config: Dict[str, Any], ui_update_callback: callable, status_callback: callable = None):
        self.driver: Optional[webdriver.Chrome] = None
        self.chat_page: Optional[ChatPage] = None
        self.chat_config = chat_config
        self.ui_update_callback = ui_update_callback
        self.status_callback = status_callback
        self.browser_queue = queue.Queue()
        self.run_threads_ref = {"active": False}
        self.comm_thread: Optional[threading.Thread] = None
        self.connection_monitor: Optional[ConnectionMonitor] = None
        self.reconnection_manager: Optional[ReconnectionManager] = None

    def start_driver(self) -> bool:
        """Initializes the Chrome WebDriver and the ChatPage handler."""
        try:
            logger.info(f"Connecting to Chrome at {DEBUGGER_ADDRESS}")
            c_options = webdriver.ChromeOptions()
            c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
            self.driver = webdriver.Chrome(options=c_options)
            self.chat_page = ChatPage(self.driver, self.chat_config)
            
            # Initialize connection monitor and reconnection manager
            # Use status_callback for browser connection status updates, not ui_update_callback (which is for topic submissions)
            connection_status_callback = self.status_callback if self.status_callback else self.ui_update_callback
            self.reconnection_manager = ReconnectionManager(self, connection_status_callback)
            self.connection_monitor = ConnectionMonitor(self, connection_status_callback, self.reconnection_manager)
            
            logger.info(f"Successfully connected to Chrome (session: {self.driver.session_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Chrome: {e}")
            self.driver = None
            self.chat_page = None
            self.connection_monitor = None
            return False

    def new_chat(self, context_text: Optional[str] = None, force_new_thread_and_init_prompt: bool = False) -> bool:
        """
        Initializes or resets the chat page by delegating to the ChatPage object.
        """
        if not self.driver or not self.chat_page:
            logger.error("Cannot initialize chat: Driver or ChatPage not available.")
            return False

        def _new_chat_operation():
            # Wrap navigate_to_initial_page with connection monitoring
            def _navigate_operation():
                return self.chat_page.navigate_to_initial_page(status_callback=self.status_callback)
            
            if self.connection_monitor:
                navigate_result = self.connection_monitor.execute_with_monitoring(_navigate_operation)
            else:
                navigate_result = self.chat_page.navigate_to_initial_page(status_callback=self.status_callback)
            
            # Handle the new tuple return format
            if isinstance(navigate_result, tuple):
                navigate_success, on_correct_page = navigate_result
                # Store the page status for later use
                self.on_correct_page = on_correct_page
            else:
                # Fallback for backward compatibility
                navigate_success = navigate_result
                self.on_correct_page = True
                
            if not navigate_success:
                return False

            if force_new_thread_and_init_prompt:
                logger.info("Forcing new thread and sending initial prompt.")
                
                # Wrap start_new_thread with connection monitoring
                def _start_thread_operation():
                    return self.chat_page.start_new_thread()
                
                if self.connection_monitor:
                    thread_success = self.connection_monitor.execute_with_monitoring(_start_thread_operation)
                else:
                    thread_success = self.chat_page.start_new_thread()
                    
                if not thread_success:
                    return False
                
                # Focus the browser window before submitting the initial prompt
                self.focus_browser_window()
                
                # Construct and send the initial prompt
                initial_prompt = self.chat_config.get("prompt_initial_content", "")
                if context_text and context_text.strip():
                    initial_prompt = f"{initial_prompt}\n\n[CONTEXT] {context_text.strip()}"
                
                if initial_prompt.strip():
                    # Wrap submit_message with connection monitoring
                    def _submit_operation():
                        return self.chat_page.submit_message(initial_prompt.strip())
                    
                    if self.connection_monitor:
                        submit_success = self.connection_monitor.execute_with_monitoring(_submit_operation)
                    else:
                        submit_success = self.chat_page.submit_message(initial_prompt.strip())
                        
                    if not submit_success:
                        logger.error("Failed to send initial prompt message.")
                        return False
                else:
                    logger.info("No initial prompt content to send.")
            
            self.chat_config["last_screenshot_check"] = datetime.now()
            return True

        try:
            return _new_chat_operation()
                
        except Exception as e:
            # Connection errors should now be handled by individual operation monitoring
            # This catch is for any remaining non-connection errors
            logger.error(f"Unexpected error in new_chat: {e}")
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

    def focus_browser_window_for_startup(self):
        """Brings the browser window to the foreground during app initialization using Selenium window management."""
        if not self.driver: 
            return
        
        try:
            # Get current window handle and switch to it to ensure focus
            current_window = self.driver.current_window_handle
            self.driver.switch_to.window(current_window)
            
            # Maximize the window to ensure it's visible and focused
            self.driver.maximize_window()
            logger.info("Browser window focused using Selenium window management (startup)")
            
        except Exception as e:
            logger.error(f"Failed to focus browser window during startup: {e}")

    def focus_browser_window(self):
        """Brings the browser window to the foreground for topic submission using pygetwindow."""
        if not self.driver: 
            return
        
        try:
            # Use pygetwindow approach that works well for topic submission
            import pygetwindow
            title = self.driver.title
            windows = pygetwindow.getWindowsWithTitle(title)
            if windows:
                win = windows[0]
                if win.isMinimized: 
                    win.restore()
                win.activate()
                logger.info(f"Browser window focused using pygetwindow (topic submission): '{title}'")
            else:
                logger.warning(f"No windows found with title: '{title}'")
                
        except Exception as e:
            logger.error(f"Failed to focus browser window for topic submission: {e}")

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

                # 0. Validate connection health before proceeding
                if self.connection_monitor and self.connection_monitor.get_connection_state() == ConnectionState.CONNECTED:
                    try:
                        if not self.test_connection_health():
                            logger.warning("Connection health check failed - skipping batch to allow reconnection.")
                            for _ in all_items_in_batch: self.browser_queue.task_done()
                            continue
                    except Exception as e:
                        if self.connection_monitor and self.connection_monitor.is_connection_error(e):
                            logger.warning(f"Connection health check detected connection error: {e}")
                            # Connection error will be handled by connection monitor, skip this batch
                            for _ in all_items_in_batch: self.browser_queue.task_done()
                            continue
                        else:
                            logger.warning(f"Connection health check error (non-connection): {e}")

                # 1. Focus the browser window to ensure it's active.
                try:
                    self.focus_browser_window()
                except Exception as e:
                    if self.connection_monitor and self.connection_monitor.is_connection_error(e):
                        logger.error(f"Connection error during focus browser window: {e}")
                        # Connection error will be handled by connection monitor, skip this batch
                        for _ in all_items_in_batch: self.browser_queue.task_done()
                        continue
                    else:
                        # Non-connection error, log but continue
                        logger.warning(f"Non-connection error during focus browser window: {e}")
                
                # 2. Prime the input field to enable the submit button
                logger.info("Work detected. Priming input field with 'Waiting...' ")
                
                def _prime_operation():
                    return self.chat_page.prime_input()
                
                try:
                    if self.connection_monitor:
                        prime_success = self.connection_monitor.execute_with_monitoring(_prime_operation)
                    else:
                        prime_success = self.chat_page.prime_input()
                        
                    if not prime_success:
                        logger.error("Could not prime input field. Skipping batch.")
                        for _ in all_items_in_batch: self.browser_queue.task_done()
                        continue
                except Exception as e:
                    if self.connection_monitor and self.connection_monitor.is_connection_error(e):
                        logger.error(f"Connection error during prime input: {e}")
                        # Connection error will be handled by connection monitor, skip this batch
                        for _ in all_items_in_batch: self.browser_queue.task_done()
                        continue
                    else:
                        logger.error(f"Non-connection error during prime input: {e}")
                        for _ in all_items_in_batch: self.browser_queue.task_done()
                        continue

                # 3. Wait for the site to be ready for submission
                logger.info("Input primed. Waiting for submit button to become active...")
                is_ready = False
                start_time = time.time()
                while time.time() - start_time < 300: # 5-minute overall timeout
                    def _ready_check():
                        return self.chat_page.is_ready_for_input()
                    
                    try:
                        if self.connection_monitor:
                            ready_status = self.connection_monitor.execute_with_monitoring(_ready_check)
                        else:
                            ready_status = self.chat_page.is_ready_for_input()
                            
                        if ready_status == SUBMISSION_SUCCESS:
                            is_ready = True
                            break
                    except Exception as e:
                        if self.connection_monitor and self.connection_monitor.is_connection_error(e):
                            logger.warning(f"Connection error during ready check: {e}")
                            # Connection error will be handled by connection monitor, skip this batch
                            for _ in all_items_in_batch: self.browser_queue.task_done()
                            # Use a flag to indicate we should skip the rest of the processing
                            is_ready = None  # Use None to indicate connection error vs timeout
                            break
                        else:
                            logger.warning(f"Non-connection error during ready check: {e}")
                            break
                        
                    if not self.run_threads_ref["active"]: return
                    time.sleep(0.2) # Small delay to prevent busy-waiting

                if is_ready is None:
                    # Connection error occurred during ready check, already handled
                    continue
                elif not is_ready:
                    logger.error("Timed out waiting for submit button. Aborting batch.")
                    self.ui_update_callback(SUBMISSION_FAILED_INPUT_UNAVAILABLE, [])
                    for _ in all_items_in_batch: self.browser_queue.task_done()
                    continue

                logger.info("Submit button is now active. Browser is ready.")

                # 4. Drain the queue to get all available items NOW that the browser is ready
                while not self.browser_queue.empty():
                    try:
                        all_items_in_batch.append(self.browser_queue.get_nowait())
                    except queue.Empty:
                        break

                # 5. Handle screenshots
                def _screenshot_operation():
                    return self._handle_screenshot_upload()
                
                try:
                    if self.connection_monitor:
                        self.connection_monitor.execute_with_monitoring(_screenshot_operation)
                    else:
                        self._handle_screenshot_upload()
                except Exception as e:
                    logger.warning(f"Screenshot upload failed due to connection error: {e}")

                # 6. Construct final payload and submit
                logger.info(f"Processing a batch of {len(all_items_in_batch)} items.")
                message_prompt = self.chat_config.get("prompt_message_content", "").strip()
                combined_topics_content = "\n".join(item['content'] for item in all_items_in_batch if item.get('content'))
                final_payload = f"{message_prompt}\n\n{combined_topics_content}" if message_prompt else combined_topics_content
                combined_topic_objects = [topic for item in all_items_in_batch for topic in item.get('topic_objects', [])]
                
                if final_payload.strip():
                    def _submit_operation():
                        return self.chat_page.submit_message(final_payload)
                    
                    try:
                        if self.connection_monitor:
                            submit_success = self.connection_monitor.execute_with_monitoring(_submit_operation)
                        else:
                            submit_success = self.chat_page.submit_message(final_payload)
                            
                        if submit_success:
                            self.ui_update_callback(SUBMISSION_SUCCESS, combined_topic_objects)
                        else:
                            self.ui_update_callback(SUBMISSION_FAILED_OTHER, [])
                    except Exception as e:
                        if self.connection_monitor and self.connection_monitor.is_connection_error(e):
                            logger.error(f"Message submission failed due to connection error: {e}")
                            # Connection error will be handled by connection monitor
                            # Don't call ui_update_callback here as the connection monitor will handle status updates
                        else:
                            logger.error(f"Message submission failed due to non-connection error: {e}")
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

    def cleanup_driver(self):
        """Safely cleanup existing driver connection."""
        try:
            if self.driver:
                logger.info("Cleaning up existing WebDriver connection...")
                try:
                    self.driver.quit()
                except Exception as e:
                    logger.warning(f"Error during driver quit: {e}")
                finally:
                    self.driver = None
                    
            if self.chat_page:
                self.chat_page = None
                
            logger.info("Driver cleanup completed.")
            
        except Exception as e:
            logger.error(f"Error during driver cleanup: {e}")

    def reinitialize_connection(self) -> bool:
        """Reinitialize driver and chat page after connection loss."""
        try:
            logger.info("Reinitializing browser connection...")
            
            # Use the same initialization logic as start_driver
            c_options = webdriver.ChromeOptions()
            c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
            self.driver = webdriver.Chrome(options=c_options)
            self.chat_page = ChatPage(self.driver, self.chat_config)
            
            # Note: We don't reinitialize connection_monitor and reconnection_manager here
            # because they are already created and we want to maintain their state
            # The connection_monitor will be updated by the ReconnectionManager
            
            logger.info(f"Browser connection reinitialized (session: {self.driver.session_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reinitialize browser connection: {e}")
            self.driver = None
            self.chat_page = None
            return False

    def test_connection_health(self) -> bool:
        """Test if current connection is healthy.
        
        Note: Being on the wrong page is NOT considered a connection failure.
        This is consistent with the startup flow which shows a warning but continues.
        """
        if not self.driver or not self.chat_page:
            logger.warning("Cannot test connection health: driver or chat_page is None")
            return False
            
        try:
            # Test basic driver functionality - these are the real connection tests
            _ = self.driver.current_url
            _ = self.driver.title
            
            # If we can access basic driver properties, the connection is healthy
            # Being on the wrong page is handled separately by navigate_to_initial_page
            logger.info("Connection health test passed - driver is responsive.")
            return True
            
        except Exception as e:
            # Only actual WebDriver connection errors should fail the health test
            if self.connection_monitor and self.connection_monitor.is_connection_error(e):
                logger.info(f"Connection health test detected connection error: {e}")
            else:
                logger.warning(f"Connection health test failed: {e}")
            return False

    def preserve_queue_state(self):
        """Preserve pending queue items during reconnection."""
        # The queue is already preserved as it's a separate object
        # This method exists for future enhancements if needed
        queue_size = self.browser_queue.qsize()
        if queue_size > 0:
            logger.info(f"Preserving {queue_size} items in browser queue during reconnection.")
        return queue_size

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