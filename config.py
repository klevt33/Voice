# config.py
import os
import pyaudio

# DLL Paths
DLL_PATHS = [
    # r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin",
    # r"C:\Program Files\NVIDIA\CUDNN\v9.10\bin\12.9"
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin",
    r"C:\Program Files\NVIDIA\CUDNN\v8\bin"
]

# Audio configuration
# MIC_INDEX_OTHERS = 8   # Voicemeeter Out B1 index
MIC_INDEX_OTHERS = 7   # Voicemeeter Out B1 index
MIC_INDEX_ME = 1       # My microphone index
SAMPLE_RATE = 44100    # Audio sampling rate
CHUNK_SIZE = 1024      # Buffer size for processing
FORMAT = pyaudio.paInt16  # Audio format
CHANNELS = 1           # Mono audio
SILENCE_THRESHOLD = 100  # Threshold for Voicemeeter
SILENCE_DURATION = 1.0   # Duration of silence to stop recording (in seconds)
MAX_RECORDING_DURATION = 120.0  # Maximum duration of a single audio fragment (in seconds)
FRAMES_PER_BUFFER = int(SAMPLE_RATE * SILENCE_DURATION / CHUNK_SIZE)  # Calculate frames needed for silence duration

# Whisper model configuration
MODELS_FOLDER = "faster_whisper_models"  # Folder to save faster_whisper models
WHISPER_MODEL = "large-v3"  # Whisper model size (tiny, base, small, medium, large-v1, large-v2)
COMPUTE_TYPE = "float16"  # Compute type (float16, int8)
LANGUAGE = "en"        # Set to English only
BEAM_SIZE = 5          # Beam size for faster-whisper

# Chat configuration
CHAT = "ChatGPT"    # Default chat to use: "Perplexity" or "ChatGPT"
DEBUGGER_ADDRESS = "localhost:9222"  # Debugging address for Chrome

# Screenshot configuration
ENABLE_SCREENSHOTS = True  # Toggle for screenshot functionality
SCREENSHOT_FOLDER = r"C:\Users\klevt\OneDrive\Pictures\Screenshots"  # Screenshot folder path
# SCREENSHOT_FOLDER = r"C:\Users\kirill.levtov\OneDrive - Perficient, Inc\Pictures\Screenshots"  # Screenshot folder path

# Chat service configurations
CHATS = {
    "Perplexity": {
        "url": "https://www.perplexity.ai/",
        "prompt_init_file": "prompt_init.txt",
        "prompt_msg_file": "prompt_msg.txt",
        "css_selector_input": "[id='ask-input']",
        "submit_button_selector": "button[aria-label='Submit']",
        "attach_files_button_selector": "button[aria-label='Attach files']",
        "file_input_selector_after_attach": "input[type='file']",
        "new_thread_button_selector": "button[data-testid='sidebar-new-thread']",
        "chat_response_selector": "[data-testid*='conversation-turn-'] .text-message",
        "generation_error_text": "Something went wrong"
    },
    "ChatGPT": {
        "url": "https://chatgpt.com/",
        "prompt_init_file": r"prompts\prompt_init.txt", # Use a separate prompt for ChatGPT
        "prompt_msg_file": r"prompts\prompt_msg.txt",   # and a separate message prompt
        # Using ID is very reliable.
        "css_selector_input": "[id='prompt-textarea']", 
        # Using data-testid is very reliable for automation.
        "submit_button_selector": "button[data-testid='send-button']", 
        # The 'Attach files' button on ChatGPT. ID is a good choice.
        "attach_files_button_selector": "[id='upload-file-btn']", 
        "file_input_selector_after_attach": "input[type='file']",
        # The "New chat" button in the top left is a link to the base URL. This is a very stable selector.
        "new_thread_button_selector": "a[data-testid='create-new-chat-button']",
        "chat_response_selector": "[data-testid*='conversation-turn-'] .text-message",
        "generation_error_text": "Something went wrong"
    }
}

# Add DLL directories at import time
for path in DLL_PATHS:
    if os.path.exists(path):
        os.add_dll_directory(path)