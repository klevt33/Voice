from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import subprocess
import time

# Specify the debugging address for the already opened Chrome browser
debugger_address = 'localhost:9222'

command = r'chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\Users\klevt\Downloads\chromeprofile"'

def navigate_to_gemini_and_submit(prompt):
  # Set up ChromeOptions and connect to the existing browser
  c_options = webdriver.ChromeOptions()
  c_options.add_experimental_option("debuggerAddress", debugger_address)

  # Initialize the WebDriver with the existing Chrome instance
  driver = webdriver.Chrome(options=c_options)

  try:
    # Navigate to Gemini
    driver.get("https://gemini.google.com")

    # Explicitly wait for the prompt input field to be present
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".ql-editor.textarea"))
    )

    # Find the prompt input field using CSS selector
    prompt_input = driver.find_element(By.CSS_SELECTOR, ".ql-editor.textarea")

    # Enter the value of the 'prompt' variable and submit with Enter key
    prompt_input.send_keys(prompt + Keys.ENTER)

  except (TimeoutException, NoSuchElementException) as e:
    print("Error: Element not found or exceeded timeout.")
    # Optionally, you can add logic to retry or handle the error differently

  #finally:
    # Close the browser window regardless of success or failure
    #driver.quit()

subprocess.Popen(command, shell=True)

# Wait for 5 seconds
time.sleep(5)

# Replace 'your_prompt_here' with your desired prompt
prompt = "Hi Gemini, How are you today?"
navigate_to_gemini_and_submit(prompt)

