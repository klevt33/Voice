# perplexity_selector_test.py
import time
import logging
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidSessionIdException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEBUGGER_ADDRESS = "localhost:9222"
PERPLEXITY_URL = "https://perplexity.ai/" # For navigation if needed

# --- Selectors for General Page Elements ---
# (Description, By_Method, Selector_String)
general_elements_to_test = [
    ("Body Tag", By.TAG_NAME, "body"),
    ("Perplexity Logo Link", By.XPATH, "//a[@href='/']//svg"), # Simpler XPath for the logo's SVG
    ("New Thread Button (aria-label)", By.CSS_SELECTOR, "button[aria-label='New Thread']"),
    ("New Thread Button (data-testid)", By.CSS_SELECTOR, "button[data-testid='sidebar-new-thread']"),
    ("Home Link (data-testid)", By.CSS_SELECTOR, "a[data-testid='sidebar-home']"),
    ("Discover Link (data-testid)", By.CSS_SELECTOR, "a[data-testid='sidebar-discover']"),
    ("Attach Files Button (aria-label)", By.CSS_SELECTOR, "button[aria-label='Attach files']"), # Ensure exact match with your config
    # The main input element, just to see if direct access fails while others might work
    ("Original Input Element ID (for reference)", By.CSS_SELECTOR, "[id='ask-input']"),
]

def get_chrome_driver_test() -> webdriver.Chrome | None:
    try:
        logging.info(f"Attempting to connect to Chrome at {DEBUGGER_ADDRESS}")
        c_options = webdriver.ChromeOptions()
        c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
        driver = webdriver.Chrome(options=c_options)
        logging.info(f"Successfully connected to Chrome instance (session: {driver.session_id})")
        
        # After connecting, check current tab
        current_handle = None
        try:
            current_handle = driver.current_window_handle
            logging.info(f"Current window handle: {current_handle}")
            logging.info(f"Active tab URL after connection: {driver.current_url}")
        except WebDriverException as e:
            logging.error(f"Error getting current URL or handle after connect: {e}. Trying to find a valid tab.")
            if driver.window_handles:
                try:
                    driver.switch_to.window(driver.window_handles[0])
                    logging.info(f"Switched to first available window. URL: {driver.current_url}")
                except Exception as e_switch:
                    logging.error(f"Failed to switch to first window: {e_switch}")
                    return None
            else:
                logging.error("No windows/tabs available after connect.")
                return None
        return driver
    except InvalidSessionIdException as e_sid:
        logging.error(f"Invalid Session ID: {e_sid}.")
        return None
    except WebDriverException as e_wd:
        logging.error(f"WebDriverException during connection: {e_wd}. Is Chrome running with debugging on {DEBUGGER_ADDRESS}?")
        return None
    except Exception as e:
        logging.error(f"Failed to connect to Chrome: {e}", exc_info=True)
        return None

def test_general_element(driver: webdriver.Chrome, description: str, by_method: str, selector: str, timeout: int = 7):
    logging.info(f"\n--- Testing General Element: {description} ---")
    logging.info(f"Using {by_method} with selector: {selector}")
    wait = WebDriverWait(driver, timeout)
    try:
        # Wait for PRESENCE of element
        element = wait.until(
            EC.presence_of_element_located((by_method, selector))
        )
        logging.info(f"SUCCESS (Presence): <{element.tag_name}> found for '{description}'.")
        logging.info(f"  ID: {element.get_attribute('id')}, Visible: {element.is_displayed()}, Enabled: {element.is_enabled()}")
        logging.info(f"  Text (first 50): '{element.text[:50]}'")
        logging.info(f"  Outer HTML (first 150): {element.get_attribute('outerHTML')[:150]}")
        return True
    except TimeoutException:
        logging.error(f"FAILED (Timeout): Element for '{description}' not found with selector '{selector}'.")
        return False
    except Exception as e:
        logging.error(f"FAILED (Exception): Error finding '{description}' with selector '{selector}': {e}")
        return False

if __name__ == "__main__":
    driver = get_chrome_driver_test()
    if driver:
        try:
            active_url = ""
            try:
                active_url = driver.current_url
                logging.info(f"Initial active tab URL: {active_url}")
            except WebDriverException as e:
                logging.error(f"Could not get initial URL, browser state might be unstable: {e}")
                # Attempt to recover by navigating (if this isn't already a problem)
                if "perplexity.ai" not in (active_url or ""):
                    logging.info(f"Attempting to navigate to {PERPLEXITY_URL} to stabilize context.")
                    try:
                        driver.get(PERPLEXITY_URL)
                        time.sleep(5) # Wait for navigation
                        active_url = driver.current_url
                        logging.info(f"URL after navigation attempt: {active_url}")
                    except Exception as e_nav:
                        logging.error(f"Failed to navigate: {e_nav}")
                        # If navigation fails, likely no point continuing
                        sys.exit("Exiting due to navigation failure after unstable context.")


            if "perplexity.ai" not in active_url:
                logging.warning(f"Current page '{active_url}' is not Perplexity. Attempting to navigate...")
                try:
                    driver.get(PERPLEXITY_URL)
                    time.sleep(7) # Wait for page to load after navigation
                    active_url = driver.current_url
                    if "perplexity.ai" not in active_url:
                        logging.error(f"Failed to navigate to Perplexity. Current URL: {active_url}. Exiting.")
                        sys.exit(1)
                    logging.info(f"Successfully navigated to Perplexity. URL: {active_url}")
                except Exception as e_nav:
                    logging.error(f"Error during navigation to Perplexity: {e_nav}")
                    sys.exit(1)
            else:
                logging.info(f"Already on Perplexity page or a subpage: {active_url}")

            settle_wait_seconds = 5 
            logging.info(f"Waiting {settle_wait_seconds}s for dynamic content to settle on the current Perplexity page...")
            time.sleep(settle_wait_seconds)

            logging.info("\n=== Testing General Page Elements (No Iframe switching yet) ===")
            success_count = 0
            for desc, by_method, sel_str in general_elements_to_test:
                if test_general_element(driver, desc, by_method, sel_str):
                    success_count += 1
                time.sleep(0.5) # Small pause between tests
            
            logging.info(f"\n--- Summary: Found {success_count} out of {len(general_elements_to_test)} general elements. ---")

            if success_count == 0:
                logging.error("COULD NOT FIND ANY of the general test elements in the main document.")
                logging.info("This suggests a fundamental issue with Selenium accessing the page content, possibly due to bot protection or the page context being invalid.")
                logging.info("Page source dump (first 10000 chars):")
                try:
                    print(driver.page_source[:10000])
                except: pass
            elif success_count < len(general_elements_to_test) -1 : # -1 because we included ask-input for reference
                 logging.warning("Found some general elements, but not all. The 'ask-input' element might still be tricky (e.g. iframe, shadow DOM, or very dynamic).")
                 if not test_general_element(driver, "Input Element ID (Re-check)", By.CSS_SELECTOR, "[id='ask-input']"):
                     logging.info("Re-confirming: 'ask-input' by ID failed in direct check.")
                     logging.info("Consider iframe check or shadow DOM if other elements are found.")

        except WebDriverException as e:
            logging.error(f"Main script WebDriverException: {e}", exc_info=True)
        except Exception as e:
            logging.error(f"An error occurred in the main script logic: {e}", exc_info=True)
        finally:
            logging.info("\nTest script finished. Browser will remain open for inspection.")
            # driver.quit()
    else:
        logging.error("Failed to get Chrome driver. Test script cannot run.")