# browser.py
import os
import glob
import logging
import time
import threading
from datetime import datetime
from typing import Dict, Optional, Any
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

def focus_browser_window(driver: Optional[webdriver.Chrome], chat_config: Dict[str, Any]):
    """
    Brings the browser window controlled by Selenium to the foreground.
    """
    if not driver:
        logger.warning("No Selenium driver provided to focus_browser_window.")
        return False
        
    try:
        current_selenium_title = driver.title
        logger.info(f"Attempting to focus browser window with current Selenium title: '{current_selenium_title}'")

        target_window = None
        
        # Attempt 1: Use exact title from Selenium
        if current_selenium_title:
            try:
                windows = pygetwindow.getWindowsWithTitle(current_selenium_title)
                if windows:
                    target_window = windows[0] # Assume first match is the one
            except Exception as e_title_match:
                logger.warning(f"Could not find window by exact Selenium title '{current_selenium_title}': {e_title_match}")

        if target_window:
            logger.info(f"Found target window: '{target_window.title}'. Attempting to activate.")
            if target_window.isMinimized:
                target_window.restore()
            target_window.activate()
            time.sleep(0.1) 
            logger.info(f"Window '{target_window.title}' activated.")
            return True
        else:
            logger.warning(f"Could not find a suitable browser window to focus.")
            return False
    except pygetwindow.PyGetWindowException as e_pgw:
        logger.error(f"pygetwindow error focusing browser window: {e_pgw} (Is a windowing system running, e.g., X11 on Linux?)")
        return False
    except Exception as e:
        logger.error(f"General error focusing browser window: {e}", exc_info=True)
        return False

def is_input_field_ready_and_no_verification(driver: webdriver.Chrome, chat_config: Dict[str, Any], timeout: int = 3) -> str:
    input_css_selector = chat_config.get("css_selector_input")
    verification_selector = chat_config.get("human_verification_text_selector")
    verification_text_content = chat_config.get("human_verification_text_content", "").lower() # Compare lowercased

    if not input_css_selector:
        logger.error("is_input_field_ready_and_no_verification: css_selector_input missing from chat_config.")
        return SUBMISSION_FAILED_OTHER

    try:
        # Check for input field clickability first
        WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))
        )
        # Input field is ready. Now, quickly check if verification text is ALSO present (it ideally shouldn't be).
        if verification_selector and verification_text_content:
            try:
                verification_elements = driver.find_elements(By.CSS_SELECTOR, verification_selector)
                for elem in verification_elements:
                    if elem.is_displayed() and verification_text_content in elem.text.lower():
                        logger.warning(f"Input field is clickable, but human verification text ('{verification_text_content}') is also visible.")
                        return SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED
            except NoSuchElementException:
                pass # Verification text not found, which is good in this path.
            except Exception as e_verif_check:
                logger.debug(f"Minor error checking for verification text when input was already ready: {e_verif_check}")


        return SUBMISSION_SUCCESS # Input ready and no explicit verification text visible

    except TimeoutException:
        logger.warning(f"Input field '{input_css_selector}' not clickable within {timeout}s.")
        # Input field is not ready. Now check if it's specifically due to human verification.
        if verification_selector and verification_text_content:
            try:
                verification_elements = driver.find_elements(By.CSS_SELECTOR, verification_selector)
                for elem in verification_elements:
                    if elem.is_displayed() and verification_text_content in elem.text.lower():
                        logger.warning(f"Human verification text ('{verification_text_content}') detected. Input field likely blocked.")
                        return SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED
            except NoSuchElementException:
                logger.info("Human verification text not found; input field unavailable for other reasons.")
            except Exception as e_verif_check:
                logger.error(f"Error while checking for verification text after input timeout: {e_verif_check}")
        
        return SUBMISSION_FAILED_INPUT_UNAVAILABLE # General input unavailable if no verification text found

    except Exception as e:
        logger.error(f"Unexpected error in is_input_field_ready_and_no_verification: {e}", exc_info=True)
        return SUBMISSION_FAILED_OTHER

def upload_screenshots(driver: webdriver.Chrome, screenshots: list, chat_config: Dict[str, Any]) -> bool:
    """
    Upload screenshots to the chat using the attach button
    
    Args:
        driver: WebDriver instance
        screenshots: List of screenshot file paths
        
    Returns:
        bool: True if upload was successful, False otherwise
    """
    if not screenshots:
        return True
    
    attach_button_selector = chat_config.get("attach_files_button_selector")
    file_input_selector = chat_config.get("file_input_selector_after_attach")

    if not attach_button_selector or not file_input_selector:
        logger.error("Attach files or file input selector missing in chat_config for upload_screenshots.")
        return False
        
    try:
        wait = WebDriverWait(driver, 5)
        
        attach_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, attach_button_selector)) # Use from config
        )
        # It's good practice to click it if it's not already opening the file dialog implicitly by finding the input
        # However, some UIs reveal the input[type=file] on hover or it's always present but hidden.
        # For Perplexity, clicking the attach button is necessary.
        attach_button.click() 
        time.sleep(0.5) # Allow time for file input to appear/become active

        # Find the file input element that appears after clicking the attach button
        file_inputs = driver.find_elements(By.CSS_SELECTOR, file_input_selector) # Use from config
        
        if not file_inputs:
            logger.error("No file input element found after clicking attach button")
            return False
        
        file_input = file_inputs[-1] # Assume last one is the relevant one
        
        if len(screenshots) > 1 and not file_input.get_attribute("multiple"):
            logger.warning("File input doesn't support multiple files, uploading one by one")
            for screenshot_path in screenshots: # Renamed to avoid conflict
                # Re-click attach and re-find file input for each if necessary, though ideally it stays open
                # For safety, we might need to re-click and re-find, but let's try without first
                # Re-finding file_input if it becomes stale or only accepts one file at a time
                # This part might need adjustment based on how the specific UI handles multiple single uploads
                current_file_inputs = driver.find_elements(By.CSS_SELECTOR, file_input_selector)
                if not current_file_inputs:
                    logger.error(f"File input disappeared while trying to upload {os.path.basename(screenshot_path)}")
                    continue # or return False
                current_file_input_element = current_file_inputs[-1]
                current_file_input_element.send_keys(screenshot_path)
                logger.info(f"Uploaded screenshot: {os.path.basename(screenshot_path)}")
                time.sleep(1) # Wait between uploads
        else:
            file_input.send_keys('\n'.join(screenshots))
            logger.info(f"Uploaded {len(screenshots)} screenshots at once or single screenshot.")
        
        time.sleep(0.5) # Wait for upload to process visually
        return True
    except Exception as e:
        logger.error(f"Screenshot upload failed: {e}", exc_info=True)            
        return False

def get_new_screenshots(screenshot_folder: str, last_check_time: datetime) -> list:
    """
    Get list of new screenshots taken since last check time
    
    Args:
        screenshot_folder: Path to the screenshots folder
        last_check_time: Timestamp of the last check
        
    Returns:
        list: List of new screenshot file paths
    """
    if not os.path.exists(screenshot_folder):
        logger.warning(f"Screenshot folder not found: {screenshot_folder}")
        return []
    
    try:
        # Get all image files in the folder
        image_extensions = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.bmp']
        all_files = []
        for ext in image_extensions:
            all_files.extend(glob.glob(os.path.join(screenshot_folder, ext)))
        
        # Filter files by modification time
        new_files = [f for f in all_files if os.path.getmtime(f) > last_check_time.timestamp()]
        
        # Convert to absolute paths to ensure they work with Selenium
        new_files = [os.path.abspath(f) for f in new_files]
        
        if new_files:
            logger.info(f"Found {len(new_files)} new screenshots since {last_check_time}")
            for file in new_files:
                logger.info(f"New screenshot: {file}")
        
        return new_files
    except Exception as e:
        logger.error(f"Error checking for new screenshots: {e}")
        return []

def get_chrome_driver() -> Optional[webdriver.Chrome]:
    """Set up ChromeOptions and connect to the existing browser
    
    Returns:
        Optional[webdriver.Chrome]: Chrome WebDriver instance or None if failed
    """
    try:
        logger.info(f"Connecting to Chrome at {DEBUGGER_ADDRESS}")
        c_options = webdriver.ChromeOptions()
        c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)

        # Initialize the WebDriver with the existing Chrome instance
        driver = webdriver.Chrome(options=c_options)
        logger.info(f"Successfully connected to Chrome (session: {driver.session_id})")
        return driver
    except Exception as e:
        logger.error(f"Failed to connect to Chrome: {e}")
        return None

def _send_initial_prompt_logic(driver: webdriver.Chrome, 
                               chat_config_resolved: Dict[str, Any], 
                               context_text: Optional[str] = None) -> bool:
    logger.info("Entering _send_initial_prompt_logic.")
    input_status_final = is_input_field_ready_and_no_verification(driver, chat_config_resolved, timeout=5)
    if input_status_final != SUBMISSION_SUCCESS:
        logger.error(f"Input field not ready or verification detected before sending initial prompt. Status: {input_status_final}")
        return False

    chat_config_resolved["last_screenshot_check"] = datetime.now()
    logger.info(f"Chat environment ready for initial prompt. Final URL: {driver.current_url}")

    initial_prompt_from_file = chat_config_resolved.get("prompt_initial_content", "")
    final_initial_prompt_to_send = initial_prompt_from_file

    if context_text and context_text.strip():
        stripped_context = context_text.strip()
        if final_initial_prompt_to_send:
            final_initial_prompt_to_send = f"{final_initial_prompt_to_send}\n\n[CONTEXT] {stripped_context}"
        else:
            final_initial_prompt_to_send = f"[CONTEXT] {stripped_context}"
        logger.info(f"Context from UI (length {len(stripped_context)}) incorporated into initial message.")
    
    requires_initial_submission = chat_config_resolved.get("requires_initial_submission", True)

    if final_initial_prompt_to_send and final_initial_prompt_to_send.strip():
        logger.info(f"Sending initial message (length {len(final_initial_prompt_to_send)}) to the chat...")
        submission_status = send_to_chat(final_initial_prompt_to_send, chat_config_resolved, submit=requires_initial_submission)
        
        if submission_status == SUBMISSION_SUCCESS:
            logger.info(f"Initial message processed successfully (submit={requires_initial_submission}).")
            return True
        else:
            logger.error(f"Failed to send/submit initial message. Status: {submission_status}")
            return False
    else:
        logger.warning("No initial prompt content and no UI context. No initial message sent.")
        return True # Environment is ready, just nothing to send.

def new_chat(driver: webdriver.Chrome, 
             chat_name_key: str, 
             loaded_config: Optional[Dict[str, Any]] = None, 
             context_text: Optional[str] = None,
             force_new_thread_and_init_prompt: bool = False) -> bool: # New parameter
    if not driver:
        logger.error("Cannot initialize chat in new_chat: No valid driver provided")
        return False
    if not loaded_config:
        logger.error(f"Error in new_chat: Chat configuration (with prompts) for {chat_name_key} not provided.")
        return False

    chat_config_resolved = loaded_config 
    chat_config_resolved["driver"] = driver 

    try:
        nav_url = chat_config_resolved.get("url", "")
        input_css_selector = chat_config_resolved.get("css_selector_input")
        new_thread_button_selector = chat_config_resolved.get("new_thread_button_selector")

        if not nav_url or not input_css_selector: # new_thread_button_selector is optional
            logger.error(f"Essential config keys (url, css_selector_input) missing for {chat_name_key} in new_chat")
            return False
        
        parsed_nav_url = urlparse(nav_url)
        domain_for_check = parsed_nav_url.netloc.replace("www.", "")
        wait_long = WebDriverWait(driver, 10)
        
        current_url_str = ""
        try:
            current_url_str = driver.current_url
        except WebDriverException: # Handle if browser is in a bad state
            logger.warning("Could not get current URL in new_chat (browser might be starting/crashed). Attempting recovery by navigating.")
            try:
                driver.get(nav_url)
                wait_long.until(EC.url_contains(domain_for_check))
                current_url_str = driver.current_url
            except Exception as e_recov:
                logger.error(f"Failed to recover by navigating to base URL in new_chat: {str(e_recov).splitlines()[0]}. Aborting.")
                return False
        
        logger.info(f"new_chat called. Current URL: {current_url_str}, Force new thread/prompt: {force_new_thread_and_init_prompt}")
        
        current_url_domain = urlparse(current_url_str).netloc.replace("www.", "")
        is_on_target_domain = (domain_for_check == current_url_domain)

        # --- Logic for handling page state based on force_new_thread_and_init_prompt ---
        if not is_on_target_domain:
            logger.info(f"Not on {domain_for_check} domain. Navigating to configured URL: {nav_url}")
            driver.get(nav_url)
            wait_long.until(lambda d: domain_for_check in d.current_url.replace("www.","") and 
                                      EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))(d))
            logger.info(f"Navigation to {nav_url} complete. Proceeding to send initial prompt.")
            # If not on target domain, we always want to send initial prompt after navigating.
            # This path implies force_new_thread_and_init_prompt should effectively be true for prompt sending.
            return _send_initial_prompt_logic(driver, chat_config_resolved, context_text)

        elif force_new_thread_and_init_prompt:
            logger.info(f"Force new thread is TRUE. Current URL: {current_url_str}. Will attempt to start fresh.")
            is_on_exact_base_nav_url = (nav_url.rstrip('/') == current_url_str.rstrip('/'))
            
            if not is_on_exact_base_nav_url and new_thread_button_selector:
                logger.info(f"On {domain_for_check} but not base URL. Clicking 'New Thread'.")
                try:
                    new_thread_button = wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, new_thread_button_selector)))
                    new_thread_button.click()
                    wait_long.until(lambda d: EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))(d) and 
                                              nav_url.rstrip('/') in d.current_url.rstrip('/')) # Wait for base URL and input
                    logger.info(f"UI transitioned after 'New Thread'. Current URL: {driver.current_url}")
                except Exception as e_click:
                    logger.warning(f"Error clicking 'New Thread': {str(e_click).splitlines()[0]}. Navigating to base URL as fallback.")
                    driver.get(nav_url)
                    wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))
            elif not is_on_exact_base_nav_url and not new_thread_button_selector:
                 logger.info(f"On {domain_for_check} but not base URL, and no new thread button. Navigating to base URL.")
                 driver.get(nav_url)
                 wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))
            else: # Already on base URL, just ensure input is ready
                 logger.info(f"Already on base URL. Ensuring input is ready for initial prompt.")
                 wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)))

            time.sleep(0.75) # Settle time
            logger.info("Additional delay complete after page stabilization for forced new thread.")
            return _send_initial_prompt_logic(driver, chat_config_resolved, context_text)

        else: # On target domain, but force_new_thread_and_init_prompt is FALSE (app startup case)
            logger.info(f"Already on {domain_for_check} domain (URL: {current_url_str}). Not forcing new thread or initial prompt as per request.")
            # Just ensure the config is set up with the driver and last_screenshot_check
            chat_config_resolved["last_screenshot_check"] = datetime.now()
            # We can do a quick check for input field presence for logging, but don't fail if not immediately found.
            try:
                WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector)))
                logger.info("Input field detected on current page.")
            except TimeoutException:
                logger.info("Input field not immediately detected on current page (might be a results page without input). This is OK for startup.")
            return True # Successfully connected, user can manually start new thread.

    except WebDriverException as e_wd:
        logger.error(f"WebDriverException in new_chat ({chat_name_key}): {str(e_wd).splitlines()[0]}", exc_info=False)
        return False
    except Exception as e:
        logger.error(f"Unexpected error in new_chat ({chat_name_key}): {str(e).splitlines()[0]}", exc_info=True)
        return False

def _get_input_element(driver: webdriver.Chrome, input_css_selector: str, timeout: int = 5) -> Optional[WebElement]:
    """
    Waits for and returns the input element if clickable.
    Returns None if not found or not clickable within timeout.
    """
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))
        )
    except TimeoutException:
        logger.warning(f"Input element '{input_css_selector}' not found or not clickable within {timeout}s.")
        return None
    except Exception as e:
        logger.error(f"Error getting input element '{input_css_selector}': {e}")
        return None

def _clear_input_element(driver: webdriver.Chrome, element: WebElement):
    """Clears the provided input element (handles div and textarea)."""
    try:
        tag_name = element.tag_name.lower()
        if tag_name == 'textarea':
            element.click() # Focus
            time.sleep(0.05)
            # Using Ctrl/Cmd+A then Delete is often more robust for textareas
            modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
            element.send_keys(modifier_key + "a")
            time.sleep(0.05)
            element.send_keys(Keys.DELETE)
            if element.get_attribute('value') != "": # Fallback if CUA keys didn't work
                element.clear() # Try Selenium's clear
                element.send_keys("") # And send empty string
            if element.get_attribute('value') != "": # Final JS fallback
                driver.execute_script("arguments[0].value = '';", element)
        elif tag_name == 'div': # For contenteditable div (Perplexity)
            driver.execute_script("arguments[0].innerHTML = '';", element)
        else: # Fallback for other types
            element.clear()

        driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
        time.sleep(0.1) # Brief pause for JS and UI to react
        logger.debug(f"Input element (tag: {tag_name}) cleared.")
    except Exception as e_clear:
        logger.warning(f"Could not reliably clear input element: {e_clear}. Proceeding.")

def _populate_input_field(driver: webdriver.Chrome, element: WebElement, content: str, chat_config: Dict[str, Any]) -> bool:
    """Populates the input field using configured method and verifies."""
    input_method = chat_config.get("input_method", "clipboard").lower()
    modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
    try:
        element.click() 
        time.sleep(0.2)
        if input_method == "clipboard":
            pyperclip.copy(content)
            logger.info(f"Content (len: {len(content)}) copied to clipboard.")
            ActionChains(driver).key_down(modifier_key).send_keys('v').key_up(modifier_key).perform()
            time.sleep(0.5)

        elif input_method == "send_keys":            
            # --- NEW LOGIC for handling newlines correctly ---
            # Split the content into lines to handle newlines properly.
            lines = content.splitlines() # Use splitlines() to handle \n and \r\n
            num_lines = len(lines)

            for i, line in enumerate(lines):
                element.send_keys(line)
                
                # If it's not the last line, send Shift+Enter to create a newline.
                # The final submission ENTER is handled by the main send_to_chat function.
                if i < num_lines - 1:
                    ActionChains(driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()
                    # A tiny pause can help with stability after a newline action.
                    time.sleep(0.02) 
            # --- END of new logic ---

            logger.info(f"Content (len: {len(content)}) sent via send_keys with Shift+Enter for newlines.")
        
        else:
            logger.error(f"Unsupported input_method: {input_method}. Cannot populate field.")
            return False

        # Verification logic remains the same
        time.sleep(0.2)
        current_value_from_field = ""
        tag_name_verify = element.tag_name.lower()
        if tag_name_verify == 'textarea': current_value_from_field = element.get_attribute('value')
        elif tag_name_verify == 'div': current_value_from_field = element.text
        
        normalized_current_value = current_value_from_field.replace('\r\n', '\n').strip()
        normalized_prompt_content = content.replace('\r\n', '\n').strip()

        if normalized_current_value == normalized_prompt_content:
            logger.info("Field value matches expected content.")
        else:
            logger.warning(f"Field value mismatch. Expected len: {len(normalized_prompt_content)}, Got len: {len(normalized_current_value)}.")
        
        return True    

    except pyperclip.PyperclipException as e_clip:
        logger.error(f"Pyperclip error during populate input: {e_clip}")
        raise 
    except Exception as e_populate:
        logger.error(f"Error populating input field: {e_populate}", exc_info=False)
        raise

def _final_explicit_clear_input(driver: webdriver.Chrome, input_css_selector: str):
    try:
        logger.info("Attempting final explicit clear of input field after submission.")
        time.sleep(0.5) # Increased delay before attempting final clear
        input_el = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))
        )
        _clear_input_element(driver, input_el) # Use the common clear helper
        
        # Verify clear
        # time.sleep(0.1)
        final_text_check = ""
        tag_name_final_check = input_el.tag_name.lower()
        if tag_name_final_check == 'textarea': final_text_check = input_el.get_attribute('value')
        elif tag_name_final_check == 'div': final_text_check = input_el.text
        
        if final_text_check and final_text_check.strip():
            logger.warning(f"Input field still contains text after final explicit clear: '{final_text_check[:50]}...'")
        else:
            logger.info("Final explicit clear of input field appears successful.")
    except TimeoutException:
        logger.warning("Could not find input field for final explicit clear (it might have disappeared, which is OK).")
    except Exception as e_final_clear:
        logger.warning(f"Could not perform final explicit clear: {e_final_clear}")

def _check_submission_processed_condition(driver, input_selector, submit_button_selector, chat_config):
    try:
        input_el = driver.find_element(By.CSS_SELECTOR, input_selector)
        tag_name = input_el.tag_name.lower()
        text_content = ""
        if tag_name == 'textarea':
            text_content = input_el.get_attribute('value')
        elif tag_name == 'div':
            text_content = input_el.text
        
        if text_content is not None and text_content.strip() == "":
            logger.debug("_check_submission_processed_condition: Input field is empty.")
            return True
    except (NoSuchElementException, StaleElementReferenceException):
        logger.debug("_check_submission_processed_condition: Input element not found/stale, assuming processing.")
        return True 

    try:
        if submit_button_selector and not is_submit_active(chat_config): 
            logger.debug("_check_submission_processed_condition: Submit button is inactive.")
            return True
    except (NoSuchElementException, StaleElementReferenceException):
        logger.debug("_check_submission_processed_condition: Submit button not found/stale.")
    except Exception as e_isa: # Catch other errors from is_submit_active
        logger.warning(f"_check_submission_processed_condition: Error checking submit button active: {e_isa}")
        
    return False

def send_to_chat(prompt_content: str, chat_config: Dict[str, Any], submit: bool = False) -> str:
    if not prompt_content:
        logger.warning("Empty prompt content, not sending")
        return SUBMISSION_NO_CONTENT

    driver = chat_config.get("driver")
    if not driver:
        logger.error("Driver missing in chat_config for send_to_chat.")
        return SUBMISSION_FAILED_OTHER
        
    input_css_selector = chat_config.get("css_selector_input")
    submit_button_selector = chat_config.get("submit_button_selector")

    if not input_css_selector:
        logger.error("css_selector_input missing from chat_config for send_to_chat.")
        return SUBMISSION_FAILED_OTHER

    input_status = is_input_field_ready_and_no_verification(driver, chat_config, timeout=5)
    if input_status != SUBMISSION_SUCCESS:
        logger.warning(f"send_to_chat: Pre-submission check failed: {input_status}. Aborting.")
        return input_status

    max_retries = 2 
    retry_count = 0

    while retry_count < max_retries:
        logger.info(f"send_to_chat attempt {retry_count + 1}/{max_retries}")
        current_input_element = None 
        try:
            current_input_element = _get_input_element(driver, input_css_selector)
            if not current_input_element:
                status_check = is_input_field_ready_and_no_verification(driver, chat_config, timeout=1)
                if status_check == SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED: return status_check
                raise TimeoutException("Failed to get clickable input element at start of attempt.")

            _clear_input_element(driver, current_input_element)
            time.sleep(0.1)

            if ENABLE_SCREENSHOTS and "last_screenshot_check" in chat_config:
                last_check_time = chat_config["last_screenshot_check"]
                new_screenshots_list = get_new_screenshots(SCREENSHOT_FOLDER, last_check_time) 
                if new_screenshots_list:
                    logger.info(f"Found {len(new_screenshots_list)} new screenshots to upload.")
                    upload_was_successful = upload_screenshots(driver, new_screenshots_list, chat_config) 
                    if not upload_was_successful:
                        logger.warning("Failed to upload some screenshots during send_to_chat.")
            
            if not _populate_input_field(driver, current_input_element, prompt_content, chat_config):
                raise Exception("Failed to populate input field.") 

            if submit:
                # --- THIS IS THE SECTION WITH THE COMMENTED-OUT RE-FETCH ---
                # # Re-fetch the input element *after* paste/populate, *before* sending ENTER
                # # This was a critical addition for reliability if re-enabled.
                # time.sleep(0.3) # Give UI a moment after populate before trying to get element for submit
                # submit_input_element = _get_input_element(driver, input_css_selector, timeout=3)
                # if not submit_input_element:
                #     logger.warning("Could not re-fetch input element before sending ENTER. Page might have changed significantly.")
                #     status_check = is_input_field_ready_and_no_verification(driver, chat_config, timeout=1)
                #     if status_check == SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED: return status_check
                #     raise TimeoutException("Failed to get input element for submit action.")
                # submit_input_element_to_use = submit_input_element # Use this if re-fetch is active
                
                submit_input_element_to_use = current_input_element 
                # --- END OF COMMENTED-OUT RE-FETCH SECTION ---

                logger.info("Submitting the prompt via ENTER key.")
                submission_action_dispatched = False
                try:
                    submit_input_element_to_use.send_keys(Keys.ENTER) 
                    submission_action_dispatched = True
                    logger.info("ENTER key sent for submission.")
                except StaleElementReferenceException as e_submit_stale:
                    logger.warning(f"StaleElementReferenceException immediately after/during sending ENTER: {str(e_submit_stale).splitlines()[0]}. Assuming ENTER was dispatched.") # Concise
                    submission_action_dispatched = True 
                except Exception as e_submit_enter: 
                    logger.error(f"Error sending ENTER key: {str(e_submit_enter).splitlines()[0]}. Attempting submit button click if configured.") # Concise
                    if submit_button_selector:
                        try:
                            submit_btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_button_selector)))
                            submit_btn.click()
                            submission_action_dispatched = True
                            logger.info("Submit button clicked successfully.")
                        except Exception as e_click_submit_btn:
                            logger.error(f"Failed to click submit button: {str(e_click_submit_btn).splitlines()[0]}") # Concise
                            raise 
                    else: 
                        raise 
                
                if ENABLE_SCREENSHOTS and "last_screenshot_check" in chat_config: 
                    chat_config["last_screenshot_check"] = datetime.now()

                if submission_action_dispatched:
                    try:
                        WebDriverWait(driver, 15).until( 
                            lambda d: _check_submission_processed_condition(d, input_css_selector, submit_button_selector, chat_config)
                        )
                        logger.info("Post-submission: AI processing or input field clear/submit inactive (robust check).")
                    except TimeoutException as e_wait_confirm: 
                        logger.warning(f"Timeout ({type(e_wait_confirm).__name__}) during post-submission confirmation wait: {e_wait_confirm.msg if hasattr(e_wait_confirm, 'msg') else str(e_wait_confirm).splitlines()[0]}. "
                                       "Assuming submission was initiated.")
                    except Exception as e_unhandled_wait: 
                        first_line_message = str(e_unhandled_wait).splitlines()[0]
                        logger.error(f"Unexpected error ({type(e_unhandled_wait).__name__}) during post-submission wait: {first_line_message}. "
                                     "Assuming submission was initiated despite wait error.")
                    
                    _final_explicit_clear_input(driver, input_css_selector)
                    return SUBMISSION_SUCCESS 
                else: 
                    logger.error("Submission action was not confirmed as dispatched. Logic error.")
            
            else: # Not submitting (submit=False)
                logger.info("Content placed into field without submission.")
                if ENABLE_SCREENSHOTS and "last_screenshot_check" in chat_config: 
                    chat_config["last_screenshot_check"] = datetime.now()
                return SUBMISSION_SUCCESS 

        except (StaleElementReferenceException, TimeoutException, NoSuchElementException) as e_retryable:
            logger.warning(f"{type(e_retryable).__name__} in send_to_chat attempt {retry_count + 1}/{max_retries}: {e_retryable.msg if hasattr(e_retryable, 'msg') else str(e_retryable).splitlines()[0]}. Retrying.")
            retry_count += 1
            time.sleep(1 + retry_count) 
            if retry_count >= max_retries:
                logger.error(f"Max retries reached due to {type(e_retryable).__name__}.")
                final_status_check = is_input_field_ready_and_no_verification(driver, chat_config, timeout=1)
                if final_status_check == SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED: return final_status_check
                return SUBMISSION_FAILED_INPUT_UNAVAILABLE
            continue 

        except pyperclip.PyperclipException as e_clip_main: 
            logger.error(f"PyperclipException in send_to_chat: {e_clip_main}")
            return SUBMISSION_FAILED_OTHER 

        except Exception as e_unexp_outer:
            if retry_count + 1 < max_retries:
                logger.error(f"Outer unexpected error in send_to_chat (attempt {retry_count + 1}/{max_retries}), retrying: {str(e_unexp_outer).splitlines()[0]}", exc_info=False)
            else: 
                logger.error(f"Outer unexpected error in send_to_chat (attempt {retry_count + 1}/{max_retries}), failing: {e_unexp_outer}", exc_info=True)
            retry_count += 1
            time.sleep(1 + retry_count)
            if retry_count >= max_retries:
                logger.error(f"Max retries reached due to unexpected error: {e_unexp_outer}")
                return SUBMISSION_FAILED_OTHER
            continue

    logger.error(f"send_to_chat failed after {max_retries} retries (outer loop exhausted).")
    return SUBMISSION_FAILED_OTHER

def load_prompt(chat_configs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Load initial and message prompts from files and add to chat configurations.
    
    Args:
        chat_configs: Dictionary of chat configurations
        
    Returns:
        Dict[str, Dict[str, Any]]: Updated configurations with prompts loaded
    """
    updated_configs = {}
    
    for chat_name, config in chat_configs.items():
        updated_config = config.copy()
        
        prompt_init_file = config.get("prompt_init_file")
        prompt_msg_file = config.get("prompt_msg_file")
        
        if prompt_init_file:
            try:
                with open(prompt_init_file, "r", encoding="utf-8") as file:
                    initial_prompt_content = file.read().strip()
                updated_config["prompt_initial_content"] = initial_prompt_content
                logger.info(f"Loaded initial prompt from {prompt_init_file} ({len(initial_prompt_content)} chars)")
            except FileNotFoundError:
                logger.error(f"Error: Initial prompt file '{prompt_init_file}' not found for {chat_name}")
            except Exception as e:
                logger.error(f"Error loading initial prompt file '{prompt_init_file}': {e}")

        if prompt_msg_file:
            try:
                with open(prompt_msg_file, "r", encoding="utf-8") as file:
                    message_prompt_content = file.read().strip()
                updated_config["prompt_message_content"] = message_prompt_content
                logger.info(f"Loaded message prompt from {prompt_msg_file} ({len(message_prompt_content)} chars)")
            except FileNotFoundError:
                logger.error(f"Error: Message prompt file '{prompt_msg_file}' not found for {chat_name}")
            except Exception as e:
                logger.error(f"Error loading message prompt file '{prompt_msg_file}': {e}")
        
        updated_configs[chat_name] = updated_config
            
    return updated_configs

def is_submit_active(chat_config: Dict[str, Any]) -> bool:
    driver = chat_config.get("driver")
    submit_button_selector = chat_config.get("submit_button_selector")

    if not driver or not submit_button_selector:
        logger.warning("Driver or submit_button_selector missing for is_submit_active.")
        return False 
    try:
        button = driver.find_element(By.CSS_SELECTOR, submit_button_selector)
        is_disabled = button.get_attribute("disabled")
        if is_disabled is not None and (is_disabled == True or is_disabled.lower() == "true" or is_disabled == ""):
            return False
        # Add other checks like class if 'disabled' attribute is not reliable
        # inactive_class = chat_config.get("submit_button_inactive_class")
        # if inactive_class and inactive_class in button.get_attribute("class").split():
        #    return False
        return True # If not explicitly disabled
    except NoSuchElementException:
        return False # Button not found implies not active
    except Exception: # Catch any other selenium errors
        return False 

def browser_communication_thread(browser_queue: queue.Queue,
                                 run_threads_ref: Dict[str, bool],
                                 chat_config: Dict[str, Any],
                                 ui_update_callback: callable):
    logger.info("Starting browser communication thread")
    send_stats = { "messages_sent": 0, "submissions": 0, "send_failures": 0 }

    while run_threads_ref["active"]:
        try:
            item_from_ui = browser_queue.get(timeout=1) 
            
            message_to_send_raw = item_from_ui["content"]
            topic_objects_for_this_submission = item_from_ui["topic_objects"]
            
            logger.info(f"RECEIVED FOR BROWSER (Thread: {threading.get_ident()}): {message_to_send_raw[:60]}...")

            if message_to_send_raw:
                submission_status = SUBMISSION_FAILED_OTHER 
                try:
                    message_prompt_text = chat_config.get("prompt_message_content", "").strip()
                    
                    if message_prompt_text:
                        full_content_to_send = f"{message_prompt_text}\n\n{message_to_send_raw}"
                    else:
                        full_content_to_send = message_to_send_raw
                        logger.warning("Message prompt (prompt_msg.txt) is empty or not loaded. Sending topics directly.")

                    logger.info(f"Preparing to send to chat (length: {len(full_content_to_send)}): {full_content_to_send[:100].replace(os.linesep, '/n')}...")
                    
                    submission_status = send_to_chat(full_content_to_send, chat_config, submit=True)

                    if submission_status == SUBMISSION_SUCCESS:
                        send_stats["messages_sent"] += 1
                        send_stats["submissions"] += 1
                        logger.info(f"Message batch submitted successfully to browser. Status: {submission_status}")
                    else:
                        send_stats["send_failures"] += 1
                        logger.error(f"Failed to send and submit message to browser. Status: {submission_status}")
                    
                    ui_update_callback(
                        submission_status, 
                        topic_objects_for_this_submission if submission_status == SUBMISSION_SUCCESS else []
                    )

                except Exception as e_proc_send: 
                    send_stats["send_failures"] += 1
                    logger.error(f"Error processing and sending message: {e_proc_send}", exc_info=True)
                    ui_update_callback(SUBMISSION_FAILED_OTHER, []) 
            
            browser_queue.task_done()

        except queue.Empty:
            continue 
        except Exception as e_thread_loop: 
            logger.error(f"Critical error in browser communication thread loop: {e_thread_loop}", exc_info=True)
            ui_update_callback(SUBMISSION_FAILED_OTHER, []) # Notify UI about a general failure
            time.sleep(5) # Pause significantly if the thread itself has issues

    total_ops = send_stats["messages_sent"] + send_stats["send_failures"]
    if total_ops > 0:
        success_rate = (send_stats["messages_sent"] / total_ops) * 100 if total_ops > 0 else 0
        logger.info(f"Browser communication stats: {send_stats['messages_sent']} messages sent "
                   f"({send_stats['submissions']} submissions), "
                   f"{send_stats['send_failures']} failures. "
                   f"Success rate: {success_rate:.1f}%")
    logger.info("Browser communication thread shutting down.")