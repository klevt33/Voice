# browser.py
import os
import glob
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Any, List
import queue
import sys
import pyperclip
from urllib.parse import urlparse

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

def new_chat(driver: webdriver.Chrome, chat_name_key: str, loaded_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not driver:
        logger.error("Cannot initialize chat: No valid driver provided")
        return None
        
    try:
        chat_config_resolved = loaded_config
        if not chat_config_resolved:
            logger.error(f"Error: Chat configuration for {chat_name_key} not found or not pre-loaded correctly.")
            return None

        # URL for actual navigation
        nav_url = chat_config_resolved.get("url", "")
        if not nav_url:
            logger.error(f"Base URL 'url' missing in config for {chat_name_key}")
            return None

        # Extract domain from nav_url for checking if we're on the site
        # e.g., from "https://www.perplexity.ai/" or "https://perplexity.ai/", domain_for_check becomes "perplexity.ai"
        parsed_nav_url = urlparse(nav_url)
        # Remove 'www.' if present for a more general domain check
        domain_for_check = parsed_nav_url.netloc.replace("www.", "")

        input_css_selector = chat_config_resolved.get("css_selector_input")
        new_thread_button_selector = chat_config_resolved.get("new_thread_button_selector")

        if not input_css_selector or not new_thread_button_selector:
            logger.error(f"Essential config keys (css_selector_input, new_thread_button_selector) missing for {chat_name_key}")
            return None
        
        wait_long = WebDriverWait(driver, 10) 
        wait_short = WebDriverWait(driver, 5)  

        current_url_str = ""
        try:
            current_url_str = driver.current_url
            logger.info(f"Current URL before new_chat logic: {current_url_str}")
        except WebDriverException as e:
            logger.error(f"Could not get current URL: {e}. Attempting to navigate to base URL: {nav_url}")
            driver.get(nav_url)
            time.sleep(3) 
            try:
                wait_long.until(
                    lambda d: domain_for_check in d.current_url.replace("www.", "") or 
                              EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))(d)
                )
                current_url_str = driver.current_url
                logger.info(f"URL after recovery navigation: {current_url_str}")
            except Exception as e_recov:
                logger.error(f"Still cannot establish a stable page after recovery navigation: {e_recov}. Aborting new_chat.")
                return None
        
        current_url_domain = urlparse(current_url_str).netloc.replace("www.", "")
        is_on_target_domain = (domain_for_check == current_url_domain)
        
        # Check if we are on the base path of the target domain (e.g. "https://www.perplexity.ai/")
        # This means the path is empty, '/', or specific known home paths.
        current_path = urlparse(current_url_str).path
        is_on_base_path_of_domain = is_on_target_domain and (current_path == "/" or current_path == "" or current_path.lower().startswith("/home") or current_path.lower().startswith("/search"))
        # If the current URL is exactly the nav_url (after stripping trailing slashes) it's also considered base.
        if nav_url.rstrip('/') == current_url_str.rstrip('/'):
            is_on_base_path_of_domain = True


        if is_on_target_domain and not (nav_url.rstrip('/') == current_url_str.rstrip('/')): # On the domain, but not the exact base nav URL
            logger.info(f"Already on a {domain_for_check} page ({current_url_str}), but not the base. Attempting to click 'New Thread'.")
            try:
                new_thread_button = wait_short.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, new_thread_button_selector))
                )
                new_thread_button.click()
                logger.info("'New Thread' button clicked successfully.")
                # Wait for UI to reset: input field is ready on *some* perplexity page.
                # The URL might change to a new search ID or back to base.
                wait_long.until(
                    lambda d: domain_for_check in d.current_url.replace("www.","") and
                              EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))(d)
                )
                logger.info(f"UI transitioned after 'New Thread'. Current URL: {driver.current_url}")
            except Exception as e_click:
                logger.warning(f"Error clicking 'New Thread' ('{new_thread_button_selector}'): {e_click}. Falling back to navigating to configured URL: {nav_url}")
                driver.get(nav_url)
                wait_long.until(lambda d: domain_for_check in d.current_url.replace("www.","") and EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))(d))
        
        elif not is_on_target_domain: # Not on the target domain at all
            logger.info(f"Not on {domain_for_check} domain. Navigating to configured URL: {nav_url}")
            driver.get(nav_url)
            wait_long.until(lambda d: domain_for_check in d.current_url.replace("www.","") and EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))(d))
        else: # Is on the target domain AND at the base nav_url, just ensure input is ready
             logger.info(f"Already on the target base URL: {current_url_str}. Ensuring input is ready.")
             wait_long.until(EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector)))


        # Final check for the input element's readiness
        try:
            logger.info(f"Final check for PRESENCE of input element: {input_css_selector}")
            input_element_present = wait_short.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, input_css_selector))
            )
            logger.info(f"Input element PRESENT. Tag: <{input_element_present.tag_name}>. Waiting for it to be CLICKABLE.")
            
            clickable_input_element = WebDriverWait(driver,10).until( # Slightly longer for clickability
                EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector))
            )
            logger.info("Input element is NOW CLICKABLE.")

        except TimeoutException:
            logger.error(f"Timeout: Input element '{input_css_selector}' not found or not interactable after navigation/new thread logic.")
            # ... (page source dump for debugging) ...
            return None

        chat_config_resolved["driver"] = driver 
        chat_config_resolved["last_screenshot_check"] = datetime.now()
        
        logger.info(f"Successfully prepared new chat environment. Final URL: {driver.current_url}")

        initial_prompt_content = chat_config_resolved.get("prompt_initial_content")
        if initial_prompt_content:
            logger.info("Sending initial prompt to the chat via clipboard method...")
            if send_to_chat(initial_prompt_content, chat_config_resolved, submit=True):
                logger.info("Initial prompt submitted successfully.")
            else:
                logger.error("Failed to send/submit initial prompt.")
        else:
            logger.warning("No initial prompt content found in configuration.")
            
        return chat_config_resolved

    except WebDriverException as e_wd:
        logger.error(f"WebDriverException in new_chat ({chat_name_key}): {e_wd}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing chat in new_chat ({chat_name_key}): {e}", exc_info=True)
        return None

def send_to_chat(prompt_content: str, chat_config: Dict[str, Any], submit: bool = False) -> bool:
    if not prompt_content:
        logger.warning("Empty prompt content, not sending")
        return False

    if not chat_config or "driver" not in chat_config:
        logger.error("Invalid chat configuration or driver missing")
        return False

    driver = chat_config["driver"] # Get driver from chat_config
    input_css_selector = chat_config.get("css_selector_input")
    if not input_css_selector:
        logger.error("css_selector_input missing from chat configuration for send_to_chat.")
        return False

    logger.debug(f"Attempting to send to chat via clipboard. Length: {len(prompt_content)}, Submit: {submit}")
    logger.debug(f"Using input CSS selector: {input_css_selector}")

    max_retries = 3
    retry_count = 0
    modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL

    while retry_count < max_retries:
        try:
            wait = WebDriverWait(driver, 10)
            prompt_input_clickable = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, input_css_selector)) # Use from config
            )
            try:
                prompt_input_clickable.clear()
                logger.debug("Prompt input field cleared via Selenium clear().")
                time.sleep(0.1)
                current_val_after_clear = prompt_input_clickable.get_attribute('value')
                # For contenteditable div, 'value' might not be the right attribute. 'textContent' or 'innerText' might be.
                # However, clear() on a contenteditable div should empty it.
                # Let's check based on tag type.
                tag_name = prompt_input_clickable.tag_name.lower()
                is_empty = False
                if tag_name == 'textarea':
                    is_empty = (current_val_after_clear == "")
                elif tag_name == 'div': # Assuming contenteditable div
                    is_empty = (prompt_input_clickable.text == "")


                if not is_empty:
                    logger.warning(f"Field (tag: {tag_name}) not empty after clear(). Trying JS clear as fallback.")
                    driver.execute_script("arguments[0].innerHTML = '';", prompt_input_clickable) # For div
                    driver.execute_script("arguments[0].value = '';", prompt_input_clickable) # For textarea
                    driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", prompt_input_clickable)
                    time.sleep(0.1)
                    if tag_name == 'textarea' and prompt_input_clickable.get_attribute('value') != "":
                         logger.error("Textarea field still not empty after JS clear. Paste might append.")
                    elif tag_name == 'div' and prompt_input_clickable.text != "":
                         logger.error("Div field still not empty after JS clear. Paste might append.")


            except Exception as e_clear:
                logger.warning(f"Could not reliably clear prompt input field: {e_clear}. Proceeding with paste.")

            if ENABLE_SCREENSHOTS and "last_screenshot_check" in chat_config:
                last_check_time = chat_config["last_screenshot_check"]
                # Ensure SCREENSHOT_FOLDER is correctly sourced, assuming it's a global from config.py
                new_screenshots_list = get_new_screenshots(SCREENSHOT_FOLDER, last_check_time) 
                
                if new_screenshots_list: # Check if there are any new screenshots
                    # Pass driver, the list of new screenshots, and chat_config to upload_screenshots
                    upload_was_successful = upload_screenshots(driver, new_screenshots_list, chat_config) 
                    if not upload_was_successful:
                        logger.warning("Failed to upload some screenshots during send_to_chat.")
                # Update screenshot check time regardless of whether new ones were found or uploaded
                chat_config["last_screenshot_check"] = datetime.now() 

            try:
                pyperclip.copy(prompt_content)
                logger.info(f"Content (len: {len(prompt_content)}) copied to clipboard.")
            except Exception as e_copy:
                logger.error(f"Failed to copy to clipboard using pyperclip: {e_copy}. Cannot paste.")
                return False

            prompt_input_clickable.click()
            time.sleep(0.2)
            ActionChains(driver).key_down(modifier_key).send_keys('v').key_up(modifier_key).perform()
            time.sleep(0.5)

            # Verification: For contenteditable div, get_attribute('value') won't work. Use .text
            current_value_from_field = ""
            tag_name_verify = prompt_input_clickable.tag_name.lower()
            if tag_name_verify == 'textarea':
                current_value_from_field = prompt_input_clickable.get_attribute('value')
            elif tag_name_verify == 'div': # contenteditable div
                 # Need to handle the case where the div might contain a <p><br></p> when "empty" after user interaction
                actual_text = prompt_input_clickable.text.strip()
                # If Perplexity wraps pasted text in <p>, we might need to find that <p>
                # For now, let's assume direct text or simple <p> wrapping.
                # A more robust check might involve getting innerHTML and parsing.
                # If prompt_content has newlines, .text might join them with spaces or lose them.
                # This verification part for contenteditable divs is tricky.
                # A simple check:
                if prompt_content.strip() == actual_text: # Simplistic check, may fail with formatting
                    current_value_from_field = prompt_content # Assume match for now for the logic below
                else:
                    # Try to get innerHTML to see the structure if it's a div
                    try:
                        inner_html = prompt_input_clickable.get_attribute('innerHTML')
                        logger.debug(f"Contenteditable div innerHTML after paste: {inner_html[:200]}")
                        # If it contains <p> tags, we might need to extract text from them.
                        # For now, if .text matches, we assume it's good.
                        # If not, the generic mismatch log will trigger.
                        current_value_from_field = actual_text # Use what .text gives for comparison logic
                    except:
                        current_value_from_field = actual_text


            normalized_current_value = current_value_from_field.replace('\r\n', '\n')
            normalized_prompt_content = prompt_content.replace('\r\n', '\n')

            if normalized_current_value == normalized_prompt_content:
                logger.info("Textarea/Div value matches expected content after paste.")
            else:
                logger.warning(
                    f"Textarea/Div value mismatch after paste. Expected len: {len(normalized_prompt_content)}, Got len: {len(normalized_current_value)}."
                )
                if abs(len(normalized_prompt_content) - len(normalized_current_value)) > 5 or len(normalized_prompt_content) < 150:
                    logger.debug(f"Expected full content (paste): '{normalized_prompt_content.replace(os.linesep, '/n')}'")
                    logger.debug(f"Actual full content (paste): '{normalized_current_value.replace(os.linesep, '/n')}'")


            if submit:
                logger.info("Submitting the prompt via ENTER key.")
                prompt_input_clickable.send_keys(Keys.ENTER)
                chat_config["last_screenshot_check"] = datetime.now()

                WebDriverWait(driver, 15).until(
                    lambda d: d.find_element(By.CSS_SELECTOR, input_css_selector).get_attribute('value') == "" or \
                              d.find_element(By.CSS_SELECTOR, input_css_selector).text == "" or \
                              not is_submit_active(chat_config) # Pass chat_config here
                )
                logger.info("Chat submitted and Perplexity appears to be processing or input field is clear.")
            else:
                logger.info("Content pasted into textarea/div without submission.")
            return True
        # ... (rest of except blocks remain similar, ensure StaleElement checks are robust) ...
        except StaleElementReferenceException:
            logger.warning(f"Stale element reference in send_to_chat (attempt {retry_count + 1}/{max_retries}), retrying...")
            retry_count += 1
            time.sleep(1.5)

        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"UI element not found or timeout in send_to_chat: {e}")
            prompt_input_exists = 'prompt_input_clickable' in locals() and locals()['prompt_input_clickable'] is not None
            if not prompt_input_exists:
                 logger.error("Prompt input field could not be found/established initially. Cannot send message.")
                 return False
            retry_count += 1
            if retry_count >= max_retries:
                 logger.error(f"Max retries reached due to Timeout/NoSuchElement in send_to_chat.")
                 return False
            time.sleep(1)

        except Exception as e:
            if pyperclip and "pyperclip" in str(e).lower():
                 logger.error(f"PyperclipException during operation: {e}. Check clipboard utilities (xclip/xsel on Linux).")
                 return False
            logger.error(f"Unexpected error in send_to_chat: {e}", exc_info=True)
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"Max retries reached in send_to_chat due to unexpected error: {e}")
                return False
            time.sleep(1)

    logger.error(f"Failed to send message via clipboard after {max_retries} retries.")
    return False

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
        logger.warning("Driver or submit_button_selector missing in chat_config for is_submit_active.")
        return False # Cannot determine, assume not active or raise error

    try:
        button = driver.find_element(By.CSS_SELECTOR, submit_button_selector) # Use from config
        # Check for 'disabled' attribute. If present (even if value is 'true' or empty), it's disabled.
        if button.get_attribute("disabled") is not None: # More robust check for disabled
            return False
        # Optionally, check for a specific class if the 'disabled' attribute isn't always used
        # inactive_class = chat_config.get("submit_button_inactive_class")
        # if inactive_class and inactive_class in button.get_attribute("class"):
        #     return False
        return True
    except NoSuchElementException:
        return False # Button not found, so not active

def browser_communication_thread(browser_queue: queue.Queue,
                               run_threads_ref: Dict[str, bool],
                               chat_config: Dict[str, Any]) -> None:
    logger.info("Starting browser communication thread")

    send_stats = {
        "messages_sent": 0,
        "submissions": 0,
        "send_failures": 0
    }

    # Initial prompt is sent by new_chat()
    while run_threads_ref["active"]:
        try:
            try:
                message_from_ui = browser_queue.get(timeout=1) # This contains context + topics
                logger.info(f"RECEIVED FOR BROWSER: {message_from_ui[:60]}..." if len(message_from_ui) > 60 else f"RECEIVED FOR BROWSER: {message_from_ui}")

                if message_from_ui:
                    try:
                        message_prompt_text = chat_config.get("prompt_message_content", "").strip() # Ensure no leading/trailing whitespace from file

                        # Combine the message prompt with the content from the UI (context + topics)
                        if message_prompt_text:
                            full_content_to_send = f"{message_prompt_text} {message_from_ui}"
                        else:
                            full_content_to_send = message_from_ui
                            logger.warning("Message prompt (prompt_msg.txt) is empty or not loaded. Sending topics directly.")

                        logger.info(f"Preparing to send to chat (length: {len(full_content_to_send)}): {full_content_to_send[:100].replace(os.linesep, '/n')}...")

                        result = send_to_chat(full_content_to_send, chat_config, submit=True)

                        if result:
                            send_stats["messages_sent"] += 1
                            send_stats["submissions"] += 1
                            logger.info(f"Message batch submitted successfully to browser.")
                        else:
                            send_stats["send_failures"] += 1
                            logger.error("Failed to send and submit message to browser.")

                    except Exception as e:
                        send_stats["send_failures"] += 1
                        logger.error(f"Error processing and sending message: {e}", exc_info=True)

                browser_queue.task_done()

            except queue.Empty:
                continue

        except Exception as e:
            logger.error(f"Error in browser communication thread: {e}", exc_info=True)
            time.sleep(1)

        if not run_threads_ref["active"]:
            break

    total_ops = send_stats["messages_sent"] + send_stats["send_failures"]
    if total_ops > 0:
        success_rate = (send_stats["messages_sent"] / total_ops) * 100 if total_ops > 0 else 0
        logger.info(f"Browser communication stats: {send_stats['messages_sent']} messages sent "
                   f"({send_stats['submissions']} submissions), "
                   f"{send_stats['send_failures']} failures. "
                   f"Success rate: {success_rate:.1f}%")

    logger.info("Browser communication thread shutting down.")