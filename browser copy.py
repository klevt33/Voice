# browser.py
# Update imports at the top of browser.py
import os
import glob
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Any, List
import threading
import queue
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException
from config import DEBUGGER_ADDRESS, MIN_CONTENT_LENGTH, CHATS, ENABLE_SCREENSHOTS, SCREENSHOT_FOLDER

# Configure logger for this module
logger = logging.getLogger(__name__)

# This will be used to synchronize access to the chat input field
# browser_input_lock = threading.Lock()

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
        
        # Click the attach button to open the file dialog
        attach_button.click()
        logger.info("Clicked attach button")
        
        # Wait for the file input to appear (it might be hidden)
        time.sleep(0.5)
        
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
                # Click attach button for each file
                attach_button.click()
                time.sleep(0.5)
                
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
    """Initialize a new chat in the browser
    
    Args:
        driver: WebDriver instance
        chat_name: Name of the chat configuration to use
        loaded_config: Pre-loaded configuration with prompt instructions
        
    Returns:
        Optional[Dict[str, Any]]: Chat configuration with driver or None if failed
    """
    if not driver:
        logger.error("Cannot initialize chat: No valid driver provided")
        return None
        
    try:
        # Use the loaded config if provided, otherwise get from CHATS
        chat_config = loaded_config if loaded_config else CHATS.get(chat_name, None)
        if not chat_config:
            logger.error(f"Error: Chat configuration for {chat_name} not found")
            return None
            
        logger.info(f"Opening URL: {chat_config['url']}")
        driver.get(chat_config["url"])
        
        # Wait for page to load (look for the chat input field)
        wait = WebDriverWait(driver, 10)
        prompt_input = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, chat_config["css_selector"]))
            )
        
        # Clear the input field (just in case)
        prompt_input.clear()
        
        # Create a new configuration dict with the driver and timestamp
        chat_config_copy = chat_config.copy()
        chat_config_copy["driver"] = driver
        chat_config_copy["last_screenshot_check"] = datetime.now()
        
        # Add prompt_established flag initialized to False
        chat_config_copy["prompt_established"] = False
        
        logger.info(f"Successfully opened new chat at {chat_config['url']}")
        return chat_config_copy

    except TimeoutException:
        logger.error(f"Timeout waiting for chat UI elements to load")
        return None
    except WebDriverException as e:
        logger.error(f"Couldn't initialize chat: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing chat: {e}")
        return None

def send_to_chat(prompt_content: str, chat_config: Dict[str, Any], submit: bool = False) -> bool:
    """Send message to chat
    
    Args:
        prompt_content: Content to send to the chat
        chat_config: Chat configuration including driver
        submit: Whether to submit the content with ENTER key
        
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    # Validate input
    if not prompt_content:
        logger.warning("Empty prompt content, not sending")
        return False
        
    if not chat_config or "driver" not in chat_config:
        logger.error("Invalid chat configuration")
        return False
    
    # Debug the input parameters
    logger.debug(f"Sending message with length {len(prompt_content)}, submit={submit}")
    logger.debug(f"Chat config keys: {list(chat_config.keys())}")
    
    # Log the CSS selector being used
    css_selector = chat_config.get("css_selector")
    if not css_selector:
        logger.error("CSS selector missing from chat configuration")
        return False
    logger.debug(f"Using CSS selector: {css_selector}")

    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Find the prompt input field
            driver = chat_config["driver"]
            css_selector = chat_config["css_selector"]
            
            # Wait for the input field to be present and enabled
            wait = WebDriverWait(driver, 5)
            prompt_input = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
            )
            
            # Check for new screenshots if enabled
            if ENABLE_SCREENSHOTS and "last_screenshot_check" in chat_config:
                last_check_time = chat_config["last_screenshot_check"]
                new_screenshots = get_new_screenshots(SCREENSHOT_FOLDER, last_check_time)
                
                if new_screenshots:
                    # Upload screenshots
                    upload_success = upload_screenshots(driver, new_screenshots)
                    if not upload_success:
                        logger.warning("Failed to upload some screenshots")
            
            # Update the last screenshot check time
            chat_config["last_screenshot_check"] = datetime.now()
            
            # Send text in small chunks with delays
            send_chunked_text(prompt_input, prompt_content)
            
            # Submit if requested
            if submit:
                logger.info("Submitting the prompt")
                time.sleep(0.2)  # Small pause before submitting
                prompt_input.send_keys(Keys.ENTER)
                
                # Update the last screenshot check time after submission
                chat_config["last_screenshot_check"] = datetime.now()
            else:
                logger.info("Content sent without submission")
                    
            return True

        except StaleElementReferenceException:
            logger.warning("Stale element reference, retrying...")
            retry_count += 1
            time.sleep(1)
            
        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"UI element not found: {e}")
            return False
            
        except Exception as e:
            logger.error(f"Error sending message to chat: {e}")
            return False
    
    logger.error(f"Failed to send message after {max_retries} retries")
    return False

def load_prompt(chat_configs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Load prompt from file and add to chat configuration
    
    Args:
        chat_configs: Dictionary of chat configurations
        
    Returns:
        Dict[str, Dict[str, Any]]: Updated configurations with prompts loaded
    """
    updated_configs = {}
    
    for chat_name, config in chat_configs.items():
        updated_config = config.copy()
        prompt_file = config.get("prompt_file")
        
        if not prompt_file:
            logger.info(f"No prompt file specified for {chat_name}")
            updated_configs[chat_name] = updated_config
            continue
            
        try:
            with open(prompt_file, "r", encoding="utf-8") as file:
                prompt_instructions = file.read()
                
            # Add the prompt instructions to the config
            updated_config["prompt_instructions"] = prompt_instructions
            logger.info(f"Loaded prompt from {prompt_file} ({len(prompt_instructions)} chars)")
            updated_configs[chat_name] = updated_config
            
        except FileNotFoundError:
            logger.error(f"Error: The file '{prompt_file}' was not found")
            updated_configs[chat_name] = updated_config
        except Exception as e:
            logger.error(f"Error loading prompt file '{prompt_file}': {e}")
            updated_configs[chat_name] = updated_config
    
    return updated_configs

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
        time.sleep(0.05)  # Small delay between chunks to ensure smooth input

def browser_communication_thread(browser_queue: queue.Queue,
                               run_threads_ref: Dict[str, bool],
                               chat_config: Dict[str, Any]) -> None:
    """Thread dedicated to sending messages to the browser"""
    logger.info("Starting browser communication thread")
    
    # Stats for monitoring performance
    send_stats = {
        "messages_sent": 0,
        "submissions": 0,
        "send_failures": 0
    }
    
    # Initialize the accumulated message and track total non-submitted text length
    accumulated_message = ""
    unsubmitted_length = 0
    
    # Set up prompt instructions only once when the thread starts
    if "prompt_instructions" in chat_config and not chat_config.get("prompt_established", False):
        try:
            logger.info("Establishing prompt instructions initially")
            driver = chat_config["driver"]
            css_selector = chat_config["css_selector"]
            
            wait = WebDriverWait(driver, 5)
            prompt_input = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
            )
            
            # Clear any existing text and set the prompt instructions
            prompt_input.clear()
            send_chunked_text(prompt_input, chat_config["prompt_instructions"])
            
            # Mark prompt as established in the config to prevent re-sending
            chat_config["prompt_established"] = True
            logger.info("Initial prompt instructions established")
            
            # Brief pause to ensure UI is ready
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to establish initial prompt: {e}")
    
    # Main processing loop
    while run_threads_ref["active"]:
        try:
            # Get the next message to send with a timeout
            try:
                message = browser_queue.get(timeout=1)
                logger.info(f"RECEIVED: {message[:50]}..." if len(message) > 50 else f"RECEIVED: {message}")
                
                # Accumulate the message
                if accumulated_message:
                    accumulated_message += " " + message
                else:
                    accumulated_message = message
                
                # Update the unsubmitted length counter
                message_length = len(message)
                unsubmitted_length += message_length
                
                # Mark this task as done
                browser_queue.task_done()
                
                # Determine if we need to submit based on total accumulated length
                should_submit = unsubmitted_length >= MIN_CONTENT_LENGTH
                
            except queue.Empty:
                # If no new message but we have accumulated content, we will send but not submit
                should_submit = False
                if not accumulated_message:
                    continue  # Nothing to do
            
            # If we have content to send
            if accumulated_message:
                try:
                    # Now send the accumulated content
                    result = send_to_chat(accumulated_message, chat_config, submit=should_submit)
                    
                    if result:
                        send_stats["messages_sent"] += 1
                        
                        if should_submit:
                            send_stats["submissions"] += 1
                            logger.info(f"Message batch submitted (length: {unsubmitted_length})")
                            
                            # Reset accumulation and length counter after submission
                            accumulated_message = ""
                            unsubmitted_length = 0
                        else:
                            logger.info(f"Message sent without submission (accumulated length: {unsubmitted_length})")
                            
                            # Since we sent without submitting, clear the accumulated message but keep track of length
                            accumulated_message = ""
                    else:
                        send_stats["send_failures"] += 1
                        logger.error("Failed to send message batch")
                        
                except Exception as e:
                    send_stats["send_failures"] += 1
                    logger.error(f"Error sending message batch: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error in browser communication thread: {e}", exc_info=True)
            time.sleep(1)
            
        # Check if we should exit
        if not run_threads_ref["active"]:
            break
    
    # Try to submit any remaining accumulated message before exiting
    if accumulated_message:
        try:
            # Force submission of remaining content
            result = send_to_chat(accumulated_message, chat_config, submit=True)
            if result:
                send_stats["messages_sent"] += 1
                send_stats["submissions"] += 1
                logger.info("Final message batch submitted")
        except Exception as e:
            send_stats["send_failures"] += 1
            logger.error(f"Error sending final message batch: {e}")
    
    # Print stats before exiting
    total = send_stats["messages_sent"] + send_stats["send_failures"]
    if total > 0:
        success_rate = (send_stats["messages_sent"] / total) * 100
        logger.info(f"Browser communication stats: sent {send_stats['messages_sent']} messages "
                   f"with {send_stats['submissions']} submissions, "
                   f"{send_stats['send_failures']} failures, "
                   f"success rate: {success_rate:.1f}%")
    
    logger.info("Browser communication thread shutting down.")