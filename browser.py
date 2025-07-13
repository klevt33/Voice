# browser.py
import os
import glob
import logging
import time
import threading
from datetime import datetime
from typing import Dict, Optional, Any, List
import queue
import sys
import pyperclip
from urllib.parse import urlparse
import pygetwindow

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException
from config import DEBUGGER_ADDRESS, ENABLE_SCREENSHOTS, SCREENSHOT_FOLDER

# Configure logger for this module
logger = logging.getLogger(__name__)

# --- Submission Status Constants ---
SUBMISSION_SUCCESS = "SUCCESS"
SUBMISSION_FAILED_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED = "HUMAN_VERIFICATION_DETECTED"
SUBMISSION_FAILED_OTHER = "OTHER_FAILURE"
SUBMISSION_NO_CONTENT = "NO_CONTENT"


class BrowserManager:
    """
    Manages all interactions with the Selenium-controlled browser,
    including initialization, navigation, and chat submissions.
    """
    def __init__(self, chat_config: Dict[str, Any], ui_update_callback: callable):
        self.driver: Optional[webdriver.Chrome] = None
        self.chat_config = chat_config
        self.ui_update_callback = ui_update_callback
        self.browser_queue = queue.Queue()
        self.run_threads_ref = {"active": False}
        self.comm_thread: Optional[threading.Thread] = None
        
        # Add driver to chat_config so helper methods can access it
        self.chat_config["driver"] = self.driver

    def start_driver(self) -> bool:
        """Initializes the Chrome WebDriver and connects to the debugging address."""
        try:
            logger.info(f"Connecting to Chrome at {DEBUGGER_ADDRESS}")
            c_options = webdriver.ChromeOptions()
            c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
            self.driver = webdriver.Chrome(options=c_options)
            self.chat_config["driver"] = self.driver # Update driver reference in config
            logger.info(f"Successfully connected to Chrome (session: {self.driver.session_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Chrome: {e}")
            self.driver = None
            self.chat_config["driver"] = None
            return False

    def new_chat(self, context_text: Optional[str] = None, force_new_thread_and_init_prompt: bool = False) -> bool:
        """
        Initializes or resets the chat page, navigating, clicking 'new thread',
        and sending an initial prompt as needed.
        """
        if not self.driver:
            logger.error("Cannot initialize chat in new_chat: No valid driver provided")
            return False

        try:
            nav_url = self.chat_config.get("url", "")
            input_css_selector = self.chat_config.get("css_selector_input")
            new_thread_button_selector = self.chat_config.get("new_thread_button_selector")

            if not nav_url or not input_css_selector:
                logger.error(f"Essential config keys (url, css_selector_input) missing for {self.chat_config.get('name')} in new_chat")
                return False
            
            parsed_nav_url = urlparse(nav_url)
            domain_for_check = parsed_nav_url.netloc.replace("www.", "")
            wait_long = WebDriverWait(self.driver, 10)
            
            current_url_str = ""
            try:
                current_url_str = self.driver.current_url
            except WebDriverException:
                logger.warning("Could not get current URL in new_chat. Attempting recovery by navigating.")
                try:
                    self.driver.get(nav_url)
                    wait_long.until(EC.url_contains(domain_for_check))
                    current_url_str = self.driver.current_url
                except Exception as e_recov:
                    logger.error(f"Failed to recover by navigating to base URL in new_chat: {str(e_recov).splitlines()[0]}. Aborting.")
                    return False
            
            logger.info(f"new_chat called. Current URL: {current_url_str}, Force new thread/prompt: {force_new_thread_and_init_prompt}")
            
            current_url_domain = urlparse(current_url_str).netloc.replace("www.", "")
            is_on_target_domain = (domain_for_check == current_url_domain)

            if not is_on_target_domain:
                logger.info(f"Not on {domain_for_check} domain. Navigating to configured URL: {nav_url}")
                self.driver.get(nav_url)
                wait_long.until(lambda d: domain_for_check in d.current_url.replace("www.","") and 
                                          EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))(d))
                logger.info(f"Navigation to {nav_url} complete. Proceeding to send initial prompt.")
                return self._send_initial_prompt(context_text)

            elif force_new_thread_and_init_prompt:
                logger.info(f"Force new thread is TRUE. Current URL: {current_url_str}. Will attempt to start fresh.")
                is_on_exact_base_nav_url = (nav_url.rstrip('/') == current_url_str.rstrip('/'))
                
                if not is_on_exact_base_nav_url and new_thread_button_selector:
                    logger.info(f"On {domain_for_check} but not base URL. Clicking 'New Thread'.")
                    try:
                        new_thread_button = wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, new_thread_button_selector)))
                        new_thread_button.click()
                        wait_long.until(lambda d: EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))(d) and 
                                                  nav_url.rstrip('/') in d.current_url.rstrip('/'))
                        logger.info(f"UI transitioned after 'New Thread'. Current URL: {self.driver.current_url}")
                    except Exception as e_click:
                        logger.warning(f"Error clicking 'New Thread': {str(e_click).splitlines()[0]}. Navigating to base URL as fallback.")
                        self.driver.get(nav_url)
                        wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))
                elif not is_on_exact_base_nav_url and not new_thread_button_selector:
                     logger.info(f"On {domain_for_check} but not base URL, and no new thread button. Navigating to base URL.")
                     self.driver.get(nav_url)
                     wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))
                else:
                     logger.info(f"Already on base URL. Ensuring input is ready for initial prompt.")
                     wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))

                time.sleep(0.75)
                logger.info("Additional delay complete after page stabilization for forced new thread.")
                return self._send_initial_prompt(context_text)

            else: # On target domain, but force_new_thread_and_init_prompt is FALSE
                logger.info(f"Already on {domain_for_check} domain. Not forcing new thread or initial prompt.")
                self.chat_config["last_screenshot_check"] = datetime.now()
                try:
                    WebDriverWait(self.driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector)))
                    logger.info("Input field detected on current page.")
                except TimeoutException:
                    logger.info("Input field not immediately detected on current page. This is OK for startup.")
                return True

        except WebDriverException as e_wd:
            logger.error(f"WebDriverException in new_chat: {str(e_wd).splitlines()[0]}", exc_info=False)
            return False
        except Exception as e:
            logger.error(f"Unexpected error in new_chat: {str(e).splitlines()[0]}", exc_info=True)
            return False

    def _send_initial_prompt(self, context_text: Optional[str] = None) -> bool:
        """
        Constructs and sends the initial prompt message as a single, self-contained action.
        This method no longer relies on the removed `send_to_chat`.
        """
        logger.info("Entering _send_initial_prompt.")
        
        # 1. Construct the final initial prompt content
        initial_prompt_from_file = self.chat_config.get("prompt_initial_content", "")
        final_initial_prompt_to_send = initial_prompt_from_file

        if context_text and context_text.strip():
            stripped_context = context_text.strip()
            if final_initial_prompt_to_send:
                final_initial_prompt_to_send = f"{final_initial_prompt_to_send}\n\n[CONTEXT] {stripped_context}"
            else:
                final_initial_prompt_to_send = f"[CONTEXT] {stripped_context}"
            logger.info("Context from UI incorporated into initial message.")
        
        if not final_initial_prompt_to_send or not final_initial_prompt_to_send.strip():
            logger.warning("No initial prompt content and no UI context. No initial message will be sent.")
            return True # Environment is ready, just nothing to send.

        # 2. Check if the browser is ready for us to start typing
        input_status_final = self._is_input_field_ready_and_no_verification(timeout=10)
        if input_status_final != SUBMISSION_SUCCESS:
            logger.error(f"Input field not ready for initial prompt. Status: {input_status_final}")
            return False

        self.chat_config["last_screenshot_check"] = datetime.now()
        logger.info(f"Chat environment ready for initial prompt. Final URL: {self.driver.current_url}")

        # 3. Perform the submission using the same helpers as the main loop
        try:
            logger.info(f"Sending initial message (length {len(final_initial_prompt_to_send)}) to the chat...")
            
            # Get the input element
            input_element = self._get_input_element()
            if not input_element:
                raise Exception("Could not get input element for initial prompt.")

            # Populate the field with the entire initial prompt
            self._populate_field(input_element, final_initial_prompt_to_send, append=False)
            
            requires_initial_submission = self.chat_config.get("requires_initial_submission", True)
            if requires_initial_submission:
                # Wait for the submit button to become clickable after populating the field
                submit_button_selector = self.chat_config.get("submit_button_selector")
                WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, submit_button_selector))
                )
                # Submit the content
                self._submit_input(input_element)
            else:
                logger.info("Initial prompt populated without submission as per configuration.")

            logger.info("Initial message processed successfully.")
            return True

        except Exception as e:
            logger.error(f"Failed to send/submit initial message. Error: {e}", exc_info=True)
            # You might want to trigger a UI status update here if possible
            # For now, returning False will propagate the failure.
            return False
        
    def _handle_screenshot_upload(self):
        """
        Encapsulates the full logic for checking for, uploading,
        and updating the timestamp for screenshots.
        """
        if not ENABLE_SCREENSHOTS or "last_screenshot_check" not in self.chat_config:
            return # Exit if screenshots are disabled or not configured

        logger.debug("Checking for new screenshots...")
        last_check_time = self.chat_config["last_screenshot_check"]
        
        # NOTE: Assumes _get_new_screenshots is defined in this file or imported.
        new_screenshots_list = self._get_new_screenshots(SCREENSHOT_FOLDER, last_check_time)
        
        if new_screenshots_list:
            logger.info(f"Found {len(new_screenshots_list)} new screenshots to upload.")
            # NOTE: Assumes _upload_screenshots is defined in this file or imported.
            upload_was_successful = self._upload_screenshots(new_screenshots_list) 
            if not upload_was_successful:
                logger.warning("Failed to upload some screenshots during send_to_chat.")
        
        # CRUCIAL: Always update the timestamp after checking, before the submission.
        # This ensures that whether we found files or not, we won't look for them again
        # in the next check until after this submission is complete.
        self.chat_config["last_screenshot_check"] = datetime.now()

    def _check_for_response_error(self) -> bool:
        """Checks the last AI response for known error text."""
        response_selector = self.chat_config.get("chat_response_selector")
        error_text = self.chat_config.get("generation_error_text")

        if not response_selector or not error_text:
            return False # Cannot check if config is missing

        try:
            # Find all response elements and get the last one
            response_elements = self.driver.find_elements(By.CSS_SELECTOR, response_selector)
            if not response_elements:
                return False # No response elements found

            last_response_text = response_elements[-1].text
            if error_text.lower() in last_response_text.lower():
                logger.error(f"Detected AI generation error text: '{error_text}' in last response.")
                return True
                
        except (NoSuchElementException, StaleElementReferenceException):
            # If the element isn't there or is stale, it's not the error message we're looking for.
            return False
        except Exception as e:
            logger.warning(f"Could not check for response error due to unexpected exception: {e}")
            return False
            
        return False

    def _submit_input(self, input_element: WebElement):
        """Handles the final action of submitting the content."""
        logger.info("Submitting the prompt...")
        try:
            # For modern UIs, sending ENTER to the input element is most reliable.
            input_element.send_keys(Keys.ENTER)
            logger.info("ENTER key sent for submission.")

            # After sending ENTER, perform post-submission checks
            time.sleep(1.0) # Give the AI a moment to start responding
            if self._check_for_response_error():
                raise Exception("AI generation error detected in response.")
            
            WebDriverWait(self.driver, 15).until(lambda d: self._check_submission_processed_condition())
            logger.info("Post-submission: AI processing started or input field cleared.")
        
        except TimeoutException:
            logger.warning("Timeout during post-submission confirmation wait. Assuming submission was initiated.")
        finally:
            # Always attempt to clear the input field for a clean state.
            self._final_explicit_clear_input()

    def _is_input_field_ready_and_no_verification(self, timeout: int = 3) -> str:
        """Checks if the input field is ready and no human verification is detected."""
        input_css_selector = self.chat_config.get("css_selector_input")
        submit_button_selector = self.chat_config.get("submit_button_selector")
        verification_selector = self.chat_config.get("human_verification_text_selector")
        verification_text = self.chat_config.get("human_verification_text_content", "").lower()

        if not input_css_selector or not submit_button_selector:
            return SUBMISSION_FAILED_OTHER

        try:
            wait = WebDriverWait(self.driver, timeout)
            # Wait for the input field to be clickable
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))
            
            # Wait for the submit button to be enabled
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_button_selector)))

            if verification_selector and verification_text:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, verification_selector)
                    if any(verification_text in elem.text.lower() for elem in elements if elem.is_displayed()):
                        logger.warning("Human verification text is visible.")
                        return SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED
                except NoSuchElementException:
                    pass # This is good.
            return SUBMISSION_SUCCESS
        except TimeoutException:
            if verification_selector and verification_text:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, verification_selector)
                    if any(verification_text in elem.text.lower() for elem in elements if elem.is_displayed()):
                        logger.warning("Human verification text detected, input blocked.")
                        return SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED
                except NoSuchElementException:
                    pass
            return SUBMISSION_FAILED_INPUT_UNAVAILABLE
        except Exception as e:
            logger.error(f"Unexpected error in _is_input_field_ready_and_no_verification: {e}", exc_info=True)
            return SUBMISSION_FAILED_OTHER

    def _get_input_element(self) -> Optional[WebElement]:
        """Waits for and returns the input element."""
        input_css_selector = self.chat_config.get("css_selector_input")
        try:
            return WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))
            )
        except TimeoutException:
            logger.warning(f"Input element '{input_css_selector}' not clickable within timeout.")
            return None

    def _clear_input_element(self, element: WebElement):
        """Clears the provided input element."""
        try:
            tag_name = element.tag_name.lower()
            if tag_name == 'div':
                self.driver.execute_script("arguments[0].innerHTML = '';", element)
            else: # textarea
                modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
                element.send_keys(modifier_key + "a", Keys.DELETE)
                if element.get_attribute('value') != "":
                    element.clear()
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
            logger.debug(f"Input element (tag: {tag_name}) cleared.")
        except Exception as e:
            logger.warning(f"Could not reliably clear input element: {e}.")

    def _populate_input_field(self, element: WebElement, content: str) -> bool:
        """Populates the input field using the configured method."""
        input_method = self.chat_config.get("input_method", "clipboard").lower()
        try:
            element.click()
            time.sleep(0.2)
            if input_method == "clipboard":
                pyperclip.copy(content)
                modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
                ActionChains(self.driver).key_down(modifier_key).send_keys('v').key_up(modifier_key).perform()
            elif input_method == "send_keys":
                for line in content.splitlines():
                    element.send_keys(line)
                    ActionChains(self.driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()
                    time.sleep(0.02)
            else:
                logger.error(f"Unsupported input_method: {input_method}.")
                return False
            
            # Verification
            time.sleep(0.2)
            tag_name = element.tag_name.lower()
            current_value = element.get_attribute('value') if tag_name == 'textarea' else element.text
            if current_value.strip() != content.strip():
                logger.warning("Field value mismatch after population.")
            return True
        except Exception as e:
            logger.error(f"Error populating input field: {e}", exc_info=True)
            return False

    def _final_explicit_clear_input(self):
        """Attempts to clear the input field after a submission."""
        input_css_selector = self.chat_config.get("css_selector_input")
        try:
            time.sleep(0.5)
            input_el = WebDriverWait(self.driver, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector)))
            self._clear_input_element(input_el)
        except TimeoutException:
            logger.warning("Could not find input field for final explicit clear (OK).")
        except Exception as e:
            logger.warning(f"Could not perform final explicit clear: {e}")

    def _check_submission_processed_condition(self) -> bool:
        """Checks if the submission has been processed by the website."""
        input_selector = self.chat_config.get("css_selector_input")
        try:
            input_el = self.driver.find_element(By.CSS_SELECTOR, input_selector)
            text_content = input_el.get_attribute('value') or input_el.text
            if text_content is not None and text_content.strip() == "":
                return True
        except (NoSuchElementException, StaleElementReferenceException):
            return True

        if not self._is_submit_active():
            return True
            
        return False

    def _is_submit_active(self) -> bool:
        """Checks if the submit button is currently active."""
        submit_button_selector = self.chat_config.get("submit_button_selector")
        if not submit_button_selector: return False
        try:
            button = self.driver.find_element(By.CSS_SELECTOR, submit_button_selector)
            return button.is_enabled()
        except (NoSuchElementException, Exception):
            return False

    def _get_new_screenshots(self, screenshot_folder: str, last_check_time: datetime) -> List[str]:
        """Gets a list of new screenshot files."""
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

    def _upload_screenshots(self, screenshots: List[str]) -> bool:
        """Uploads screenshots to the chat."""
        attach_button_selector = self.chat_config.get("attach_files_button_selector")
        file_input_selector = self.chat_config.get("file_input_selector_after_attach")
        if not attach_button_selector or not file_input_selector: return False
        
        try:
            wait = WebDriverWait(self.driver, 5)
            attach_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, attach_button_selector)))
            attach_button.click()
            time.sleep(0.5)

            file_input = self.driver.find_elements(By.CSS_SELECTOR, file_input_selector)[-1]
            file_input.send_keys('\n'.join(screenshots))
            logger.info(f"Uploaded {len(screenshots)} screenshots.")
            time.sleep(0.5)
            return True
        except Exception as e:
            logger.error(f"Screenshot upload failed: {e}", exc_info=True)
            return False

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
        """Signals the browser communication thread to stop and waits for it to exit."""
        if self.run_threads_ref.get("active", False):
            logger.info("Stopping browser communication thread...")
            self.run_threads_ref["active"] = False # Signal the loop to terminate
            
            if self.comm_thread and self.comm_thread.is_alive():
                # The join() call waits for the thread to finish its current loop and exit.
                # The loop's timeout on queue.get() ensures it won't block forever.
                self.comm_thread.join(timeout=5)
                if self.comm_thread.is_alive():
                    logger.warning("Browser communication thread did not exit within the timeout.")
                else:
                    logger.info("Browser communication thread shut down successfully.")
            self.comm_thread = None # Clean up the thread object
        else:
            logger.info("Browser communication thread was not active or already stopped.")
 
    def _is_input_field_available(self) -> bool:
        """Checks if the main input field is available and clickable."""
        if not self.driver:
            return False
        
        input_css_selector = self.chat_config.get("css_selector_input")
        if not input_css_selector:
            return False

        try:
            WebDriverWait(self.driver, 0.1).until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))
            return True
        except TimeoutException:
            return False
        except Exception as e:
            logger.error(f"Error checking for input field availability: {e}")
            return False
        
    def _populate_field(self, element: WebElement, content: str):
        """
        Populates the input field by overwriting its content using the clipboard.
        This is the single, fast method for all population actions.
        """
        # We always clear the element first for a predictable state.
        self._clear_input_element(element)
        
        try:
            # The only supported method is clipboard, which is fast and reliable.
            pyperclip.copy(content)
            modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
            
            # A Select All (Ctrl+A) followed by a Paste (Ctrl+V) is a robust
            # way to ensure the field content is exactly what we want.
            ActionChains(self.driver).click(element).key_down(modifier_key).send_keys("a").key_up(modifier_key).perform()
            time.sleep(0.05) # Small pause for stability
            ActionChains(self.driver).key_down(modifier_key).send_keys("v").key_up(modifier_key).perform()
            
            time.sleep(0.2)
            logger.debug(f"Clipboard paste complete. Total length={len(content)}")

        except Exception as e:
            logger.error(f"Error populating input field via clipboard: {e}", exc_info=True)
            raise # Re-raise the exception to fail the current submission attempt.

    def _browser_communication_loop(self):
        """
        Main loop for browser interaction. Implements the 'Prime and Submit' logic.
        """
        logger.info("Starting browser communication loop with 'Prime and Submit' logic.")
        while self.run_threads_ref["active"]:
            try:
                # 1. GET WORK: Block until at least one item is in the queue.
                first_item = self.browser_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            all_items_in_batch = [first_item]
            
            try:
                # 2. PRIME THE INPUT FIELD
                logger.info("Work detected. Priming input field with 'Waiting...'")
                input_element = self._get_input_element()
                if not input_element:
                    logger.error("Could not get input element to prime. Skipping batch.")
                    self.browser_queue.task_done()
                    continue
                
                self._populate_field(input_element, "Waiting...")

                # 3. WAIT FOR TRUE READINESS (while draining the queue)
                submit_button_selector = self.chat_config.get("submit_button_selector")
                logger.info(f"Input primed. Waiting for submit button ('{submit_button_selector}') to become active...")
                
                is_ready = False
                start_time = time.time()
                while time.time() - start_time < 300: # 5-minute overall timeout
                    try:
                        if WebDriverWait(self.driver, 0.2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_button_selector))):
                            is_ready = True
                            break
                    except TimeoutException:
                        pass # Expected, continue polling.
                    
                    while not self.browser_queue.empty():
                        try:
                            all_items_in_batch.append(self.browser_queue.get_nowait())
                            logger.debug(f"Added item to batch while waiting. New size: {len(all_items_in_batch)}.")
                        except queue.Empty:
                            break
                    
                    if not self.run_threads_ref["active"]: return

                if not is_ready:
                    logger.error("Timed out waiting for submit button. Aborting batch.")
                    # Mark all items as done to clear them from the queue
                    for _ in all_items_in_batch: self.browser_queue.task_done()
                    continue

                logger.info("Submit button is now active. Browser is ready.")

                # 4. HANDLE SCREENSHOTS
                # This is the correct place to call the handler. After the browser
                # is confirmed to be ready, but before we populate the final payload.
                self._handle_screenshot_upload()

                # 5. CONSTRUCT PAYLOAD & SUBMIT
                logger.info(f"Processing a batch of {len(all_items_in_batch)} items.")
                
                message_prompt = self.chat_config.get("prompt_message_content", "").strip()
                combined_topics_content = "\n".join(item['content'] for item in all_items_in_batch if item.get('content'))
                final_payload = f"{message_prompt}\n\n{combined_topics_content}" if message_prompt else combined_topics_content
                combined_topic_objects = [topic for item in all_items_in_batch for topic in item.get('topic_objects', [])]
                
                if final_payload.strip():
                    # Overwrite the "Waiting..." text with the full, final payload.
                    self._populate_field(input_element, final_payload)
                    self._submit_input(input_element)
                    self.ui_update_callback(SUBMISSION_SUCCESS, combined_topic_objects)
                else:
                    self.ui_update_callback(SUBMISSION_NO_CONTENT, combined_topic_objects)

            except Exception as e:
                logger.error(f"Failed to process and submit batch: {e}", exc_info=True)
                self.ui_update_callback(SUBMISSION_FAILED_OTHER, [])

            # Mark all items in the processed batch as done
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
