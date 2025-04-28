from selenium import webdriver

# Specify the debugging address for the already opened Chrome browser
debugger_address = 'localhost:9222'

# Set up ChromeOptions and connect to the existing browser
c_options = webdriver.ChromeOptions()
c_options.add_experimental_option("debuggerAddress", debugger_address)

# Initialize the WebDriver with the existing Chrome instance
driver = webdriver.Chrome(options=c_options)

# Now, you can interact with the already opened Chrome browser
driver.get('https://gemini.google.com')