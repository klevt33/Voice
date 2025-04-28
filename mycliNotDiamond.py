import click
import torch
import speech_recognition as sr
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from whisper_mic import WhisperMic

# Launch a Chrome instance in debugging mode:
# chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\Users\klevt\Downloads\chromeprofile"
 
# Specify the debugging address for the already opened Chrome browser
debugger_address = "localhost:9222"

def get_chrome_driver():
    # Set up ChromeOptions and connect to the existing browser
    c_options = webdriver.ChromeOptions()
    c_options.add_experimental_option("debuggerAddress", debugger_address)

    # Initialize the WebDriver with the existing Chrome instance
    return webdriver.Chrome(options=c_options)

def send_to_gpt(driver, prompt):
    try:
        # Find the prompt input field using CSS selector
        prompt_input = driver.find_element(By.ID, "chat-promt")

        # Enter the value of the 'prompt' variable and submit with Enter key
        prompt_input.send_keys(prompt + Keys.ENTER)

    except (TimeoutException, NoSuchElementException) as e:
        print("Error: Element not found or exceeded timeout.")  

@click.command()
@click.option("--model", default="medium", help="Model to use", type=click.Choice(["tiny","base", "small","medium","large","large-v2","large-v3"]))
@click.option("--device", default=("cuda" if torch.cuda.is_available() else "cpu"), help="Device to use", type=click.Choice(["cpu","cuda","mps"]))
@click.option("--english", default=False, help="Whether to use English model",is_flag=True, type=bool)
@click.option("--verbose", default=False, help="Whether to print verbose output", is_flag=True,type=bool)
@click.option("--energy", default=300, help="Energy level for mic to detect", type=int)
@click.option("--dynamic_energy", default=False,is_flag=True, help="Flag to enable dynamic energy", type=bool)
@click.option("--pause", default=0.8, help="Pause time before entry ends", type=float)
@click.option("--save_file",default=False, help="Flag to save file", is_flag=True,type=bool)
@click.option("--loop", default=False, help="Flag to loop", is_flag=True,type=bool)
@click.option("--dictate", default=False, help="Flag to dictate (implies loop)", is_flag=True,type=bool)
@click.option("--mic_index", default=None, help="Mic index to use", type=int)
@click.option("--list_devices",default=False, help="Flag to list devices", is_flag=True,type=bool)
@click.option("--faster",default=False, help="Use faster_whisper implementation", is_flag=True,type=bool)
@click.option("--hallucinate_threshold",default=400, help="Raise this to reduce hallucinations.  Lower this to activate more often.", is_flag=True,type=int)
def main(model: str, english: bool, verbose: bool, energy:  int, pause: float, dynamic_energy: bool, save_file: bool, device: str, loop: bool, dictate: bool,mic_index:Optional[int],list_devices: bool,faster: bool,hallucinate_threshold:int) -> None:
    mic_names = sr.Microphone.list_microphone_names()
    
    if list_devices:
        print("Possible devices: ", mic_names)
        return
    
    driver = get_chrome_driver()
    print("Chrome session id:", driver.session_id)
    
    # Print the name of the microphone device with the specified index
    try:
        print("Selected device: ", mic_names[mic_index])
    except IndexError:
        print("Error: Specified microphone index is out of range.")
    
    mic = WhisperMic(model=model, english=english, verbose=verbose, energy=energy, pause=pause, dynamic_energy=dynamic_energy, save_file=save_file, device=device,mic_index=mic_index,implementation=("faster_whisper" if faster else "whisper"),hallucinate_threshold=hallucinate_threshold)

    if not loop:
        try:
            while True:
                result = mic.listen(timeout=20)
                if len(result) > 20:
                    print("Sending to Chrome: " + result[:50] + "...")
                    send_to_gpt(driver, result)
                else:
                    print("Short prompt: " + result)
        except KeyboardInterrupt:
            print("Operation interrupted successfully")
        finally:
            if save_file:
                mic.file.close()
    else:
        try:
            mic.listen_loop(dictate=dictate,phrase_time_limit=2)
        except KeyboardInterrupt:
            print("Operation interrupted successfully")
        finally:
            if save_file:
                mic.file.close()

if __name__ == "__main__":
    main()
