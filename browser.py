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

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException
from config import DEBUGGER_ADDRESS, CHATS, ENABLE_SCREENSHOTS, SCREENSHOT_FOLDER

# Configure logger for this module
logger = logging.getLogger(__name__)

def upload_screenshots(driver: webdriver.Chrome, screenshots: list) -> bool:
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
    
    try:
        # Find the attach button using the specific HTML provided
        wait = WebDriverWait(driver, 5)
        
        # Looking for the paperclip button with the specific aria-label
        attach_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Attach files. ']"))
        )
        
        # Find the file input element that appears after clicking the attach button
        # This is typically a hidden input element
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        
        if not file_inputs:
            logger.error("No file input element found after clicking attach button")
            return False
        
        # Use the last file input element (most likely the one that just appeared)
        file_input = file_inputs[-1]
        
        # For multiple files, we need to ensure the file input allows multiple selections
        if len(screenshots) > 1 and not file_input.get_attribute("multiple"):
            logger.warning("File input doesn't support multiple files, uploading one by one")
            for screenshot in screenshots:                
                # Find the file input again
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if not file_inputs:
                    continue
                
                file_input = file_inputs[-1]
                file_input.send_keys(screenshot)
                logger.info(f"Uploaded screenshot: {os.path.basename(screenshot)}")
                time.sleep(1)  # Wait between uploads
        else:
            # Join all screenshot paths with \n for multiple file upload
            file_input.send_keys('\n'.join(screenshots))
            logger.info(f"Uploaded {len(screenshots)} screenshots at once")
        
        # Wait for the file upload to complete
        time.sleep(0.5)
        
        return True
    except Exception as e:
        logger.error(f"Screenshot upload failed: {e}")            
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

def new_chat(driver: webdriver.Chrome, chat_name: str, loaded_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not driver:
        logger.error("Cannot initialize chat: No valid driver provided")
        return None
        
    try:
        chat_config = loaded_config if loaded_config else CHATS.get(chat_name, None)
        if not chat_config:
            logger.error(f"Error: Chat configuration for {chat_name} not found")
            return None
            
        logger.info(f"Opening URL: {chat_config['url']}")
        driver.get(chat_config["url"])
        
        wait = WebDriverWait(driver, 10)
        # Ensure the prompt input element is at least present on the page
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, chat_config["css_selector"])))
        
        chat_config_copy = chat_config.copy()
        chat_config_copy["driver"] = driver
        chat_config_copy["last_screenshot_check"] = datetime.now()
        
        logger.info(f"Successfully opened new chat at {chat_config['url']}")

        # Send the initial prompt using the updated send_to_chat
        initial_prompt_content = chat_config_copy.get("prompt_initial_content")
        if initial_prompt_content:
            logger.info("Sending initial prompt to the chat...")
            # send_to_chat now handles clearing (via JS) and setting value (via JS)
            if send_to_chat(initial_prompt_content, chat_config_copy, submit=True):
                logger.info("Initial prompt submitted successfully.")
            else:
                logger.error("Failed to send/submit initial prompt.")
                # Consider if this is fatal for new_chat; returning None would indicate failure.
                # return None 
        else:
            logger.warning("No initial prompt content found in configuration.")
            
        return chat_config_copy

    except TimeoutException:
        logger.error(f"Timeout waiting for chat UI elements to load for new_chat")
        return None
    except WebDriverException as e:
        logger.error(f"WebDriverException in new_chat: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing chat in new_chat: {e}", exc_info=True)
        return None

def send_to_chat(prompt_content: str, chat_config: Dict[str, Any], submit: bool = False) -> bool:
    if not pyperclip:
        logger.error("pyperclip is not available. Cannot use clipboard paste method. Skipping send_to_chat.")
        return False # Or fallback to another method if designed

    if not prompt_content:
        logger.warning("Empty prompt content, not sending")
        return False

    if not chat_config or "driver" not in chat_config:
        logger.error("Invalid chat configuration")
        return False

    logger.debug(f"Attempting to send to chat via clipboard. Length: {len(prompt_content)}, Submit: {submit}")
    css_selector = chat_config.get("css_selector")
    if not css_selector:
        logger.error("CSS selector missing from chat configuration")
        return False
    logger.debug(f"Using CSS selector: {css_selector}")

    max_retries = 3
    retry_count = 0

    # Determine modifier key for paste based on platform
    modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL

    while retry_count < max_retries:
        try:
            driver = chat_config["driver"]
            wait = WebDriverWait(driver, 10)
            
            # 1. Ensure element is present and then clear it
            prompt_input_clickable = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
            )
            try:
                prompt_input_clickable.clear()
                logger.debug("Prompt input field cleared via Selenium clear().")
                # Add a tiny delay for the clear action to fully register if needed
                time.sleep(0.1) 
                # Verify it's empty
                if prompt_input_clickable.get_attribute('value') != "":
                    logger.warning("Field not empty after clear(). Trying JS clear as fallback.")
                    driver.execute_script("arguments[0].value = '';", prompt_input_clickable)
                    driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", prompt_input_clickable)
                    time.sleep(0.1)
                    if prompt_input_clickable.get_attribute('value') != "":
                         logger.error("Field still not empty after JS clear. Paste might append.")

            except Exception as e_clear:
                logger.warning(f"Could not reliably clear prompt input field: {e_clear}. Proceeding with paste.")


            # Screenshot logic (if enabled)
            if ENABLE_SCREENSHOTS and "last_screenshot_check" in chat_config:
                # ... (screenshot logic remains the same)
                pass # Placeholder for brevity
            chat_config["last_screenshot_check"] = datetime.now()


            # 2. Copy to clipboard and paste
            try:
                pyperclip.copy(prompt_content)
                logger.info(f"Content (len: {len(prompt_content)}) copied to clipboard.")
            except Exception as e_copy:
                logger.error(f"Failed to copy to clipboard using pyperclip: {e_copy}. Cannot paste.")
                return False # Critical failure for this method

            # Ensure the element is focused before pasting
            prompt_input_clickable.click() # Click to ensure focus
            time.sleep(0.2) # Small delay to ensure focus takes effect

            logger.debug(f"Sending PASTE command ({modifier_key} + V)")
            ActionChains(driver).key_down(modifier_key).send_keys('v').key_up(modifier_key).perform()
            
            # Give a moment for the paste operation to complete and text to appear
            time.sleep(0.5) # Adjust if needed, depends on system/browser responsiveness

            # 3. Verify the content
            current_value = prompt_input_clickable.get_attribute('value')
            # Normalize line endings for comparison, as clipboard/paste might change them
            normalized_current_value = current_value.replace('\r\n', '\n')
            normalized_prompt_content = prompt_content.replace('\r\n', '\n')

            if normalized_current_value == normalized_prompt_content:
                logger.info("Textarea value matches expected content after paste.")
            else:
                logger.warning(
                    f"Textarea value mismatch after paste. Expected len: {len(normalized_prompt_content)}, Got len: {len(normalized_current_value)}."
                )
                if abs(len(normalized_prompt_content) - len(normalized_current_value)) > 5 or len(normalized_prompt_content) < 150:
                    logger.debug(f"Expected full content (paste): '{normalized_prompt_content.replace(os.linesep, '/n')}'")
                    logger.debug(f"Actual full content (paste): '{normalized_current_value.replace(os.linesep, '/n')}'")
                # This mismatch is a significant issue for the clipboard method's reliability.
                # Depending on strictness, you might want to `return False` or retry.


            # 4. Submit if requested
            if submit:
                logger.info("Submitting the prompt via ENTER key.")
                prompt_input_clickable.send_keys(Keys.ENTER)
                chat_config["last_screenshot_check"] = datetime.now()

                WebDriverWait(driver, 15).until(
                    lambda d: d.find_element(By.CSS_SELECTOR, css_selector).get_attribute('value') == "" or \
                              not is_submit_active(chat_config)
                )
                logger.info("Chat submitted and Perplexity appears to be processing or input field is clear.")
            else:
                logger.info("Content pasted into textarea without submission.")

            return True

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
            # Check if it's a pyperclip specific error if it wasn't caught earlier
            if pyperclip and "pyperclip" in str(e).lower():
                 logger.error(f"PyperclipException during operation: {e}. Check clipboard utilities (xclip/xsel on Linux).")
                 return False # Pyperclip issue is critical for this strategy
            logger.error(f"Unexpected error in send_to_chat: {e}", exc_info=True)
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"Max retries reached in send_to_chat due to unexpected error: {e}")
                return False
            time.sleep(1)

    logger.error(f"Failed to send message via clipboard after {max_retries} retries.")
    return False

# The new_chat function would remain the same as your last working version,
# as it just calls this send_to_chat function.
# Ensure new_chat looks like this for context:
def new_chat(driver: webdriver.Chrome, chat_name: str, loaded_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not driver:
        logger.error("Cannot initialize chat: No valid driver provided")
        return None
        
    try:
        chat_config = loaded_config if loaded_config else CHATS.get(chat_name, None)
        if not chat_config:
            logger.error(f"Error: Chat configuration for {chat_name} not found")
            return None
            
        logger.info(f"Opening URL: {chat_config['url']}")
        driver.get(chat_config["url"])
        
        # Wait for page to load and input field to be clickable for the initial clear/paste
        wait = WebDriverWait(driver, 10)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, chat_config["css_selector"])))
        
        chat_config_copy = chat_config.copy()
        chat_config_copy["driver"] = driver
        chat_config_copy["last_screenshot_check"] = datetime.now()
        
        logger.info(f"Successfully opened new chat at {chat_config['url']}")

        initial_prompt_content = chat_config_copy.get("prompt_initial_content")
        if initial_prompt_content:
            logger.info("Sending initial prompt to the chat via clipboard method...")
            # send_to_chat now uses clipboard
            if send_to_chat(initial_prompt_content, chat_config_copy, submit=True):
                logger.info("Initial prompt submitted successfully.")
            else:
                logger.error("Failed to send/submit initial prompt using clipboard method.")
                # return None # Optionally, make this a fatal error for new_chat
        else:
            logger.warning("No initial prompt content found in configuration.")
            
        return chat_config_copy

    except TimeoutException:
        logger.error(f"Timeout waiting for chat UI elements to load for new_chat")
        return None
    except WebDriverException as e:
        logger.error(f"WebDriverException in new_chat: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing chat in new_chat: {e}", exc_info=True)
        return None

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
    try:
        driver = chat_config["driver"]
        button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Submit"]')
        if button.get_attribute("disabled") or "cursor-default" in button.get_attribute("class"):
            return False
        return True
    except NoSuchElementException:
        return False

def send_chunked_text(prompt_input: WebElement, text: str, chunk_size: int = 50) -> None:
    """Send text in small chunks to avoid input lag
    
    Args:
        prompt_input: WebElement representing the input field
        text: Text to send
        chunk_size: Size of each chunk to send
    """
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i+chunk_size]
        prompt_input.send_keys(chunk)
        time.sleep(0.05)

# send_prompt function is removed as it's no longer needed with the new prompt logic.

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