# chat_page.py
import logging
import time
import sys
from typing import Optional, List
from urllib.parse import urlparse
import pyperclip
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

logger = logging.getLogger(__name__)

# Submission Status Constants
SUBMISSION_SUCCESS = "SUCCESS"
SUBMISSION_FAILED_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED = "HUMAN_VERIFICATION_DETECTED"
SUBMISSION_FAILED_OTHER = "OTHER_FAILURE"

class ChatPage:
    """
    Encapsulates all Selenium interactions with a specific chat website's page.
    """
    def __init__(self, driver: WebDriver, config: dict):
        self.driver = driver
        self.config = config
        self.wait_long = WebDriverWait(self.driver, 10)
        self.wait_short = WebDriverWait(self.driver, 3)

    def navigate_to_initial_page(self, status_callback: callable = None) -> tuple[bool, bool]:
        """Checks if browser is on the correct AI chat page and shows warning if not.
        
        Returns:
            tuple[bool, bool]: (success, on_correct_page)
        """
        nav_url = self.config.get("url", "")
        if not nav_url:
            logger.error("Cannot navigate: 'url' not in chat config.")
            return False, False
        
        try:
            parsed_nav_url = urlparse(nav_url)
            domain_for_check = parsed_nav_url.netloc.replace("www.", "")
            
            # Try to get current URL - this may fail if there's no execution context
            try:
                current_url = self.driver.current_url
                current_url_domain = urlparse(current_url).netloc.replace("www.", "")
                
                # Check if already on the correct domain
                if domain_for_check == current_url_domain:
                    logger.info(f"Browser is on correct domain: {domain_for_check}")
                    return True, True
                else:
                    # Browser is not on the correct page - show warning and continue
                    logger.warning(f"Browser is not on expected AI chat page. Expected: {domain_for_check}, Current: {current_url_domain}")
                    
                    # Update UI status with warning if callback is provided
                    if status_callback:
                        try:
                            status_callback("warning", f"Browser not on {domain_for_check} - please navigate manually")
                            logger.info("UI status updated with navigation warning")
                        except Exception as callback_error:
                            logger.warning(f"Failed to update UI status: {callback_error}")
                    
                    return True, False
                    
            except Exception as url_error:
                # Can't get current URL (execution context error, etc.) - assume wrong page
                logger.warning(f"Cannot determine current browser page (execution context error). Expected: {domain_for_check}")
                logger.debug(f"URL access error: {url_error}")
                
                # Update UI status with warning if callback is provided
                if status_callback:
                    try:
                        status_callback("warning", f"Browser not on {domain_for_check} - please navigate manually")
                        logger.info("UI status updated with navigation warning")
                    except Exception as callback_error:
                        logger.warning(f"Failed to update UI status: {callback_error}")
                
                return True, False
            
        except Exception as e:
            logger.error(f"Error in navigate_to_initial_page: {e}")
            return True, False  # Continue anyway, assume wrong page

    def _wait_for_manual_navigation_with_retry(self, target_domain: str, timeout: int = 60) -> bool:
        """Wait for manual navigation using window title detection."""
        logger.info(f"Waiting for manual navigation to {target_domain}...")
        logger.info("Navigate to the URL in your Chrome browser, then the app will continue.")
        
        # Map domains to expected window title keywords
        domain_keywords = {
            "chatgpt.com": "chatgpt",
            "perplexity.ai": "perplexity"
        }
        
        expected_keyword = domain_keywords.get(target_domain.lower(), target_domain.split('.')[0])
        
        start_time = time.time()
        check_interval = 3  # Check every 3 seconds
        
        while time.time() - start_time < timeout:
            try:
                # Re-activate window periodically
                if (time.time() - start_time) % 15 < check_interval:  # Every 15 seconds
                    self._activate_browser_window_safe()
                
                # Try URL check first (preferred method)
                try:
                    current_domain = urlparse(self.driver.current_url).netloc.replace("www.", "")
                    if target_domain == current_domain:
                        logger.info(f"Successfully detected navigation to {target_domain} via URL")
                        return True
                except:
                    pass  # Fall back to title check
                
                # Fallback: Check window title (more reliable when execution context is broken)
                try:
                    import pygetwindow
                    chrome_windows = [w for w in pygetwindow.getAllWindows() if 'chrome' in w.title.lower()]
                    for window in chrome_windows:
                        if expected_keyword.lower() in window.title.lower():
                            logger.info(f"Successfully detected navigation to {target_domain} via window title: '{window.title}'")
                            return True
                except Exception as title_error:
                    logger.debug(f"Title check failed: {title_error}")
                    
                time.sleep(check_interval)
                
            except Exception as e:
                logger.debug(f"Navigation check failed, retrying: {e}")
                time.sleep(check_interval)
        
        logger.warning(f"Timeout waiting for manual navigation to {target_domain}")
        logger.info("Assuming navigation was completed manually and continuing...")
        return True  # Assume success to avoid blocking the app



    def _suggest_manual_navigation(self, target_url: str):
        """Suggest manual navigation when automatic methods fail."""
        logger.info("=" * 60)
        logger.info("MANUAL NAVIGATION REQUIRED")
        logger.info("=" * 60)
        logger.info(f"Please manually navigate to: {target_url}")
        logger.info("This helps avoid bot detection systems.")
        logger.info("Once you're on the correct page, the automation will continue.")
        logger.info("=" * 60)

    def _wait_for_manual_navigation(self, target_domain: str, timeout: int = 60) -> bool:
        """Wait for user to manually navigate to the target domain."""
        logger.info(f"Waiting up to {timeout} seconds for manual navigation to {target_domain}...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                current_domain = urlparse(self.driver.current_url).netloc.replace("www.", "")
                if target_domain == current_domain:
                    logger.info(f"Successfully detected navigation to {target_domain}")
                    return True
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Error checking current URL: {e}")
                time.sleep(1)
        
        logger.error(f"Timeout waiting for manual navigation to {target_domain}")
        return False

    def _navigate_via_javascript(self, url: str, domain_for_check: str) -> bool:
        """Navigate using JavaScript (less detectable than driver.get)."""
        try:
            logger.info(f"Attempting JavaScript navigation to {url}")
            
            # Test if we have a valid execution context first
            try:
                self.driver.execute_script("return document.readyState;")
                logger.info("JavaScript execution context is available")
            except Exception as context_error:
                logger.warning(f"No valid JavaScript execution context: {context_error}")
                # Fall back to direct navigation
                return self._navigate_direct_fallback(url, domain_for_check)
            
            # Ensure we have a valid execution context
            current_url = self.driver.current_url
            logger.info(f"Current URL before navigation: {current_url}")
            
            # Use JavaScript to navigate
            self.driver.execute_script(f"window.location.href = '{url}';")
            
            # Wait for navigation with a reasonable timeout
            logger.info(f"Waiting for navigation to domain: {domain_for_check}")
            self.wait_long.until(EC.url_contains(domain_for_check))
            
            new_url = self.driver.current_url
            logger.info(f"Successfully navigated via JavaScript to: {new_url}")
            return True
            
        except Exception as e:
            logger.error(f"JavaScript navigation failed: {e}")
            # Try direct navigation as fallback
            logger.info("Attempting direct navigation as fallback")
            return self._navigate_direct_fallback(url, domain_for_check)

    def _navigate_direct_fallback(self, url: str, domain_for_check: str) -> bool:
        """Fallback to direct navigation when JavaScript fails."""
        try:
            logger.info(f"Using direct navigation to {url}")
            self.driver.get(url)
            self.wait_long.until(EC.url_contains(domain_for_check))
            logger.info("Successfully navigated via direct method")
            return True
        except Exception as e:
            logger.error(f"Direct navigation also failed: {e}")
            # If everything fails, suggest manual navigation
            self._suggest_manual_navigation(url)
            return False

    def start_new_thread(self) -> bool:
        """Clicks the 'new thread' button and waits for the page to be ready."""
        nav_url = self.config.get("url", "")
        new_thread_selector = self.config.get("new_thread_button_selector")
        input_selector = self.config.get("css_selector_input")

        if not all([nav_url, new_thread_selector, input_selector]):
            logger.error("Cannot start new thread: Essential config keys are missing.")
            return False

        try:
            logger.info("Attempting to start a new thread.")
            # Use JavaScript to click the element, which can be more reliable
            new_thread_button = self.wait_long.until(EC.presence_of_element_located((By.CSS_SELECTOR, new_thread_selector)))
            self.driver.execute_script("arguments[0].click();", new_thread_button)

            # Wait for the UI to update, which often includes a URL change and the input field becoming ready.
            self.wait_long.until(
                lambda d: EC.element_to_be_clickable((By.CSS_SELECTOR, input_selector))(d) and \
                          nav_url.rstrip('/') in d.current_url.rstrip('/')
            )
            logger.info(f"UI transitioned after 'New Thread'. Current URL: {self.driver.current_url}")
            time.sleep(0.75) # Allow for any final page stabilization
            return True
        except Exception as e:
            logger.warning(f"Error clicking 'New Thread', falling back to navigation: {e}")
            result = self.navigate_to_initial_page()
            # Handle tuple return format
            if isinstance(result, tuple):
                return result[0]  # Return just the success boolean
            return result

    def is_ready_for_input(self) -> str:
        """Checks if the input field is ready and no human verification is detected."""
        input_selector = self.config.get("css_selector_input")
        submit_selector = self.config.get("submit_button_selector")
        verification_selector = self.config.get("human_verification_text_selector")
        verification_text = self.config.get("human_verification_text_content", "").lower()

        try:
            self.wait_short.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_selector)))
            self.wait_short.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_selector)))

            if verification_selector and verification_text:
                elements = self.driver.find_elements(By.CSS_SELECTOR, verification_selector)
                if any(verification_text in elem.text.lower() for elem in elements if elem.is_displayed()):
                    logger.warning("Human verification detected.")
                    return SUBMISSION_FAILED_HUMAN_VERIFICATION_DETECTED
            return SUBMISSION_SUCCESS
        except TimeoutException:
            return SUBMISSION_FAILED_INPUT_UNAVAILABLE
        except Exception as e:
            logger.error(f"Unexpected error checking for input readiness: {e}")
            return SUBMISSION_FAILED_OTHER

    def prime_input(self) -> bool:
        """Enters placeholder text to enable the submit button."""
        input_selector = self.config.get("css_selector_input")
        try:
            input_element = self.wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_selector)))
            self._populate_field(input_element, "Waiting...")
            return True
        except Exception as e:
            logger.error(f"Could not prime input field: {e}")
            return False

    def submit_message(self, message: str) -> bool:
        """Populates the input field and submits the message."""
        input_selector = self.config.get("css_selector_input")
        try:
            input_element = self.wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_selector)))
            self._populate_field(input_element, message)
            self._submit_input(input_element)
            return True
        except Exception as e:
            logger.error(f"Failed to submit message: {e}")
            return False

    def _populate_field(self, element: WebElement, content: str):
        """Populates the input field by overwriting its content."""
        self._clear_input_element(element)
        pyperclip.copy(content)
        modifier_key = Keys.COMMAND if sys.platform == 'darwin' else Keys.CONTROL
        ActionChains(self.driver).click(element).key_down(modifier_key).send_keys("a").key_up(modifier_key).perform()
        time.sleep(0.05)
        ActionChains(self.driver).key_down(modifier_key).send_keys("v").key_up(modifier_key).perform()
        logger.debug(f"Clipboard paste complete. Total length={len(content)}")

    def _clear_input_element(self, element: WebElement):
        """Clears the provided input element."""
        try:
            tag_name = element.tag_name.lower()
            if tag_name == 'div':
                self.driver.execute_script("arguments[0].innerHTML = '';", element)
            else: # textarea
                element.send_keys(Keys.CONTROL + "a", Keys.DELETE)
                if element.get_attribute('value') != "":
                    element.clear()
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
        except Exception as e:
            logger.warning(f"Could not reliably clear input element: {e}.")

    def _submit_input(self, input_element: WebElement):
        """Handles the final action of submitting the content."""
        logger.info("Submitting the prompt...")
        input_element.send_keys(Keys.ENTER)
        time.sleep(1.0)
        if self._check_for_response_error():
            raise Exception("AI generation error detected in response.")
        self.wait_long.until(lambda d: self._check_submission_processed_condition())
        logger.info("Post-submission: AI processing started or input field cleared.")

    def _check_submission_processed_condition(self) -> bool:
        """Checks if the submission has been processed by the website."""
        input_selector = self.config.get("css_selector_input")
        try:
            input_el = self.driver.find_element(By.CSS_SELECTOR, input_selector)
            text_content = input_el.get_attribute('value') or input_el.text
            return text_content is not None and text_content.strip() == ""
        except (NoSuchElementException, StaleElementReferenceException):
            return True
        return False

    def _check_for_response_error(self) -> bool:
        """Checks the last AI response for known error text."""
        response_selector = self.config.get("chat_response_selector")
        error_text = self.config.get("generation_error_text")
        if not response_selector or not error_text:
            return False
        try:
            response_elements = self.driver.find_elements(By.CSS_SELECTOR, response_selector)
            if not response_elements:
                return False
            return error_text.lower() in response_elements[-1].text.lower()
        except (NoSuchElementException, StaleElementReferenceException):
            return False
        return False

    def upload_screenshots(self, screenshots: List[str]) -> bool:
        """Uploads screenshots to the chat."""
        attach_button_selector = self.config.get("attach_files_button_selector")
        file_input_selector = self.config.get("file_input_selector_after_attach")
        if not attach_button_selector or not file_input_selector: return False
        
        try:
            attach_button = self.wait_short.until(EC.element_to_be_clickable((By.CSS_SELECTOR, attach_button_selector)))
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


    def _suggest_manual_navigation(self, target_url: str):
        """Suggest manual navigation when automatic methods fail."""
        logger.info("=" * 60)
        logger.info("MANUAL NAVIGATION REQUIRED")
        logger.info("=" * 60)
        logger.info(f"Please manually navigate to: {target_url}")
        logger.info("This helps avoid bot detection systems.")
        logger.info("Once you're on the correct page, the automation will continue.")
        logger.info("=" * 60)