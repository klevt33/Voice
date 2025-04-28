#Old solution
import os
os.add_dll_directory(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin")
os.add_dll_directory(r"C:\Program Files\NVIDIA\CUDNN\v8\bin")

import pyaudio
import numpy as np
import time
from datetime import datetime
import signal
import sys
import threading
import queue
import torch
from faster_whisper import WhisperModel
import gc
import io
import wave

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Enable TF32 for better performance
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

# Configuration variables
MIC_INDEX_OTHERS = 8   # Voicemeeter Out B1 index
MIC_INDEX_ME = 1       # My microphone index
SAMPLE_RATE = 44100    # Audio sampling rate
CHUNK_SIZE = 1024      # Buffer size for processing
FORMAT = pyaudio.paInt16  # Audio format
CHANNELS = 1           # Mono audio
SILENCE_THRESHOLD = 100  # Threshold for Voicemeeter
SILENCE_DURATION = 1.0   # Duration of silence to stop recording (in seconds)
FRAMES_PER_BUFFER = int(SAMPLE_RATE * SILENCE_DURATION / CHUNK_SIZE)  # Calculate frames needed for silence duration
MODELS_FOLDER = "faster_whisper_models"  # Folder to save faster_whisper models
WHISPER_MODEL = "medium"  # Whisper model size (tiny, base, small, medium, large-v1, large-v2)
COMPUTE_TYPE = "float16"  # Compute type (float16, int8)
LANGUAGE = "en"       # Set to English only
BEAM_SIZE = 5         # Beam size for faster-whisper
MIN_CONTENT_LENGTH = 20  # Minimum content length for chat submission
CHAT = "Perplexity"  # Default chat to use
DEBUGGER_ADDRESS = "localhost:9222"  # Debugging address for Chrome

# Global variables for signal handling
run_threads = True
audio = None
audio_queue = queue.Queue()  # Queue for in-memory audio data

# Dictionary to store thread-specific data
mic_data = {
    "ME": {
        "index": MIC_INDEX_ME,
        "recording": False,
        "frames": [],
        "stream": None
    },
    "OTHERS": {
        "index": MIC_INDEX_OTHERS,
        "recording": False,
        "frames": [],
        "stream": None
    }
}

# Dictionary to store chat configurations
chats = {
    "Perplexity": {
        "url": "https://perplexity.ai/",
        "css_selector": "textarea[placeholder^='Ask']",
        "prompt_file": "pprompt.txt"
    }
}

class AudioSegment:
    """Class to store audio data in memory"""
    def __init__(self, frames, sample_rate, channels, sample_width, source):
        self.frames = frames
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.source = source  # "ME" or "OTHERS" to identify the microphone source
    
    def get_wav_bytes(self):
        """Convert frames to WAV file bytes in memory"""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b''.join(self.frames))
        wav_buffer.seek(0)
        return wav_buffer.read()

def handle_exit(sig, frame):
    """Handle Ctrl+C by processing the current recording and exiting all threads"""
    global run_threads, audio
    print("\nCtrl+C detected. Processing last recordings and shutting down...")
    
    # Stop the global flag first
    run_threads = False
    
    # Close all streams
    for source, data in mic_data.items():
        if data["stream"] is not None:
            try:
                if data["stream"].is_active():
                    data["stream"].stop_stream()
                data["stream"].close()
            except Exception:
                pass
        
        # Process any remaining recordings
        if data["recording"] and len(data["frames"]) > 0:
            process_recording(data["frames"], source)
    
    if audio:
        audio.terminate()
    
    # Allow some time for threads to clean up
    time.sleep(2)
    sys.exit(0)

def process_recording(frames, source):
    """Process the recorded frames and add to in-memory queue"""
    if not frames:
        return
    
    print(f"Processing new audio segment from {source}")
    
    # Create audio segment object
    audio_segment = AudioSegment(
        frames=frames,
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        sample_width=audio.get_sample_size(FORMAT),
        source=source
    )
    
    # Add to queue for processing
    audio_queue.put(audio_segment)
    print(f"Audio segment from {source} queued for transcription")

def get_audio_level(data):
    """Calculate the audio level using absolute values"""
    data_np = np.frombuffer(data, dtype=np.int16)
    return np.mean(np.abs(data_np))

def recording_thread(source):
    """Generic thread for handling audio recording from a specific microphone"""
    global audio, run_threads
    
    # Get the mic data for this source
    mic = mic_data[source]
    mic_index = mic["index"]
    
    # Get device info
    try:
        device_info = audio.get_device_info_by_index(mic_index)
        print(f"Using {source} microphone: {device_info['name']} (index {mic_index})")
    except Exception as e:
        print(f"Error accessing {source} microphone with index {mic_index}: {e}")
        return
    
    # Open the input stream
    try:
        mic["stream"] = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=mic_index,
            frames_per_buffer=CHUNK_SIZE
        )
    except Exception as e:
        print(f"Error opening {source} audio stream: {e}")
        return
    
    print(f"Ready to record from {source} microphone. Listening for sound...")
    
    # Main recording loop
    while run_threads:
        # Wait for sound to begin
        print(f"Waiting for sound on {source} microphone...")
        while run_threads:
            try:
                data = mic["stream"].read(CHUNK_SIZE, exception_on_overflow=False)
                level = get_audio_level(data)
                if level > SILENCE_THRESHOLD:
                    print(f"Sound detected on {source} microphone. Recording started.")
                    mic["recording"] = True
                    mic["frames"] = [data]  # Start with the first chunk that triggered recording
                    break
            except Exception as e:
                # Only print errors if we're still supposed to be running
                if run_threads:
                    print(f"Error reading from {source} stream: {e}")
                    time.sleep(1)
            
            if not run_threads:
                break
        
        # Record until silence
        silence_counter = 0
        while mic["recording"] and run_threads:
            try:
                data = mic["stream"].read(CHUNK_SIZE, exception_on_overflow=False)
                mic["frames"].append(data)
                
                # Check for silence
                level = get_audio_level(data)
                
                if level <= SILENCE_THRESHOLD:
                    silence_counter += 1
                    if silence_counter >= FRAMES_PER_BUFFER:
                        print(f"Silence detected on {source} microphone. Recording stopped.")
                        mic["recording"] = False
                else:
                    silence_counter = 0
            except Exception as e:
                # Only print errors if we're still supposed to be running
                if run_threads:
                    print(f"Error during {source} recording: {e}")
        
        # Process the recording if we have data
        if mic["frames"] and len(mic["frames"]) > 0:
            process_recording(mic["frames"], source)
            mic["frames"] = []
    
    # Clean up
    try:
        if mic["stream"].is_active():
            mic["stream"].stop_stream()
        mic["stream"].close()
    except Exception:
        pass

def transcription_thread():
    """Thread that processes audio segments and converts speech to text using faster_whisper"""
    global run_threads
    
    print(f"Initializing faster_whisper ({WHISPER_MODEL} model)...")
    
    # Determine device type
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
        
    # Create models folder if it doesn't exist
    if not os.path.exists(MODELS_FOLDER):
        os.makedirs(MODELS_FOLDER)
    
    # Initialize the model
    try:
        # Load the faster_whisper model
        print("About to load faster_whisper model...")
        model = WhisperModel(
            WHISPER_MODEL,
            device=device,
            compute_type=COMPUTE_TYPE if device == "cuda" else "int8",
            download_root=MODELS_FOLDER
        )
        print("faster_whisper model loaded successfully")
    except Exception as e:
        print(f"Error initializing faster_whisper: {e}")
        print(f"Detailed error: {str(e)}")
        run_threads = False
        return
    
    print("Speech recognition thread ready.")
    
    # Main processing loop
    while run_threads:
        try:
            # Get the next audio segment with a timeout to allow checking run_threads
            try:
                audio_segment = audio_queue.get(timeout=1)
            except queue.Empty:
                continue
                
            # Process the audio segment
            source_prefix = f"[{audio_segment.source}]"
            # print(f"\nTranscribing {source_prefix} audio recorded at {audio_segment.timestamp}")
            
            try:
                # Get audio data as WAV bytes
                audio_data = audio_segment.get_wav_bytes()
                
                # Transcribe with faster_whisper - specifying English language
                segments, info = model.transcribe(
                    io.BytesIO(audio_data),
                    language=LANGUAGE,
                    beam_size=BEAM_SIZE,
                    word_timestamps=False
                )
                
                # Process the transcript without timestamps
                transcript_text = ""
                segment_list = list(segments)  # Convert generator to list
                
                if not segment_list:
                    print(f"{source_prefix} No speech detected.")
                else:
                    # Combine all segments into one continuous text
                    for segment in segment_list:
                        transcript_text += segment.text + " "
                    
                    full_transcript = source_prefix + " " + transcript_text.strip()
                    # Print the partial transcript with source prefix
                    print(f"SENDING: {full_transcript[:100]}...")  # Print first 100 characters for brevity
                    send_to_chat(full_transcript)  # Send the full transcript to the chat
                
                audio_queue.task_done()
                    
            except Exception as e:
                print(f"Error transcribing {source_prefix} audio: {e}")
                # Put it back in the queue to try again later
                audio_queue.put(audio_segment)
                time.sleep(1)
                
        except Exception as e:
            print(f"Error in transcription thread: {e}")
            time.sleep(1)
            
        # Check if we should exit
        if not run_threads:
            break
    
    # Clean up resources
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    
    print("Transcription thread shutting down.")

def get_chrome_driver():
    # Set up ChromeOptions and connect to the existing browser
    c_options = webdriver.ChromeOptions()
    c_options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)

    # Initialize the WebDriver with the existing Chrome instance
    return webdriver.Chrome(options=c_options)

def new_chat(driver):
    try:
        driver.get(chats[CHAT]["url"])
        chats[CHAT]["driver"] = driver  # Store the driver in the chat configuration
        print(f"Opened new chat at {chats[CHAT]['url']}")

    except WebDriverException as e:
        print(f"Couldn't initiate a new chat: {e}")

def load_prompt():
    try:
        prompt_file = chats[CHAT]["prompt_file"]
        if prompt_file:
            with open(prompt_file, "r") as file:
                prompt_instructions = file.read()
            # Add the new key-value pair to the dictionary
            chats[CHAT]["prompt_instructions"] = prompt_instructions
            print(f"Loaded prompt from {prompt_file}")
    except FileNotFoundError:
        print(f"Error: The file '{prompt_file}' was not found.")
    except Exception as e:
        print(f"Error: An unexpected error occurred: {e}")

def send_to_chat(prompt_content):
    try:
        # Find the prompt input field using a simpler and more stable CSS selector
        prompt_input = chats[CHAT]["driver"].find_element(By.CSS_SELECTOR, chats[CHAT]["css_selector"])

        # Prepare the prompt based on whether the textarea is empty
        full_prompt = prompt_content if prompt_input.get_attribute('value') else chats[CHAT]["prompt_instructions"] + " >>> " + prompt_content
        full_prompt += Keys.ENTER if len(prompt_content) >= MIN_CONTENT_LENGTH else ""  # Only send if content length is sufficient

        # Send the prompt
        prompt_input.send_keys(full_prompt)

    except (TimeoutException, NoSuchElementException) as e:
        print("Error: Element not found or exceeded timeout.")
 
def main():
    global audio
    
    driver = get_chrome_driver()
    print(f"Chrome session id: {driver.session_id}")
    new_chat(driver)
    load_prompt()

    # Initialize PyAudio once for all threads
    audio = pyaudio.PyAudio()
    
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_exit)
    
    # Create and start the recording threads
    recorder_me = threading.Thread(target=recording_thread, args=("ME",))
    recorder_me.daemon = True
    recorder_me.start()
    
    recorder_others = threading.Thread(target=recording_thread, args=("OTHERS",))
    recorder_others.daemon = True
    recorder_others.start()
    
    # Create and start the transcription thread
    transcriber = threading.Thread(target=transcription_thread)
    transcriber.daemon = True
    transcriber.start()
    
    print("Press Ctrl+C to exit")
    
    # Keep the main thread alive until Ctrl+C
    try:
        while run_threads:
            time.sleep(0.1)
    except KeyboardInterrupt:
        handle_exit(None, None)

if __name__ == "__main__":
    main()