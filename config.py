# config.py
import os
import pyaudio

# DLL Paths
DLL_PATHS = [
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin",
    r"C:\Program Files\NVIDIA\CUDNN\v8\bin"
]

# Audio configuration
MIC_INDEX_OTHERS = 8   # Voicemeeter Out B1 index
MIC_INDEX_ME = 1       # My microphone index
SAMPLE_RATE = 44100    # Audio sampling rate
CHUNK_SIZE = 1024      # Buffer size for processing
FORMAT = pyaudio.paInt16  # Audio format
CHANNELS = 1           # Mono audio
SILENCE_THRESHOLD = 100  # Threshold for Voicemeeter
SILENCE_DURATION = 1.0   # Duration of silence to stop recording (in seconds)
FRAMES_PER_BUFFER = int(SAMPLE_RATE * SILENCE_DURATION / CHUNK_SIZE)  # Calculate frames needed for silence duration

# Whisper model configuration
MODELS_FOLDER = "faster_whisper_models"  # Folder to save faster_whisper models
WHISPER_MODEL = "medium"  # Whisper model size (tiny, base, small, medium, large-v1, large-v2)
COMPUTE_TYPE = "float16"  # Compute type (float16, int8)
LANGUAGE = "en"        # Set to English only
BEAM_SIZE = 5          # Beam size for faster-whisper

# Chat configuration
CHAT = "Perplexity"    # Default chat to use
DEBUGGER_ADDRESS = "localhost:9222"  # Debugging address for Chrome

# Screenshot configuration
ENABLE_SCREENSHOTS = True  # Toggle for screenshot functionality
SCREENSHOT_FOLDER = r"C:\Users\kirill.levtov\OneDrive - Perficient, Inc\Pictures\Screenshots"  # Screenshot folder path

# Chat service configurations
CHATS = {
    "Perplexity": {
        "url": "https://www.perplexity.ai/",
        "prompt_init_file": "prompt_init.txt",
        "prompt_msg_file": "prompt_msg.txt",
        "css_selector_input": "[id='ask-input']",
        "submit_button_selector": "button[aria-label='Submit']",
        # Corrected selector for Attach Files button
        "attach_files_button_selector": "button[aria-label='Attach files']",
        "file_input_selector_after_attach": "input[type='file']",
        # Add selector for the "New Thread" button (can be aria-label or data-testid)
        # Using data-testid is often more robust if available and consistently used
        "new_thread_button_selector": "button[data-testid='sidebar-new-thread']" 
                                     # Or: "button[aria-label='New Thread']" if data-testid isn't stable
    }
}

# Add DLL directories at import time
for path in DLL_PATHS:
    if os.path.exists(path):
        os.add_dll_directory(path)