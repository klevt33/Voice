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
# Microphone devices are now automatically detected:
# - ME: Uses system default microphone
# - OTHERS: Uses system default speakers loopback (requires pyaudiowpatch)
CHUNK_SIZE = 1024      # Buffer size for processing
SAMPLE_RATE = 44100    # Audio sampling rate
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

# API Transcription Configuration
GROQ_API_KEY_ENV_VAR = "GROQ_API_KEY"  # Environment variable name for Groq API key
GROQ_MODEL = "whisper-large-v3"        # Groq Whisper model to use
API_REQUEST_TIMEOUT = 30.0             # Timeout for API requests in seconds
API_RETRY_COUNT = 3                    # Number of retry attempts for failed API requests
API_RETRY_BACKOFF = 2.0               # Exponential backoff multiplier for retries

# Transcription Method Configuration
DEFAULT_TRANSCRIPTION_METHOD = "auto"  # "local", "api", "auto" (auto = prefer local GPU if available)
ENABLE_FALLBACK = True                 # Enable automatic fallback between transcription methods
FALLBACK_RETRY_LIMIT = 3              # Maximum number of fallback attempts before giving up
FALLBACK_COOLDOWN_PERIOD = 60.0       # Cooldown period in seconds before retrying failed method

# Chat configuration
CHAT = "Perplexity"    # Default chat to use: "Perplexity" or "ChatGPT"
DEBUGGER_ADDRESS = "localhost:9222"  # Debugging address for Chrome

# Screenshot configuration
ENABLE_SCREENSHOTS = False  # Toggle for screenshot functionality
# SCREENSHOT_FOLDER = r"C:\Users\klevt\OneDrive\Pictures\Screenshots"  # Screenshot folder path
SCREENSHOT_FOLDER = r"C:\Users\kirill.levtov\OneDrive - Perficient, Inc\Pictures\Screenshots"  # Screenshot folder path

# Topic storage configuration
# Folder where captured topics will be automatically saved to files
# Each audio session (Listen ON/OFF cycle) creates a new timestamped file
# Topics are saved independently of UI interactions (submit/delete/copy)
TOPIC_STORAGE_FOLDER = r"C:\Transcripts"  # Default storage path

# Chat service configurations
CHATS = {
    "Perplexity": {
        "url": "https://www.perplexity.ai/",
        "prompt_init_file": r"prompts\prompt_init.txt",
        "prompt_msg_file": r"prompts\prompt_msg.txt",
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

# Configuration validation functions
def get_groq_api_key():
    """Get Groq API key from environment variable"""
    return os.getenv(GROQ_API_KEY_ENV_VAR)

def is_groq_api_available():
    """Check if Groq API is available (has valid API key)"""
    api_key = get_groq_api_key()
    return api_key is not None and len(api_key.strip()) > 0

def validate_transcription_config():
    """Validate transcription configuration and return validation results"""
    validation_results = {
        "groq_api_available": is_groq_api_available(),
        "groq_api_key_configured": get_groq_api_key() is not None,
        "config_valid": True,
        "warnings": [],
        "errors": []
    }
    
    # Check API configuration
    if not validation_results["groq_api_key_configured"]:
        validation_results["warnings"].append(
            f"Groq API key not found in environment variable '{GROQ_API_KEY_ENV_VAR}'. API transcription will be unavailable."
        )
    
    # Validate timeout values
    if API_REQUEST_TIMEOUT <= 0:
        validation_results["errors"].append("API_REQUEST_TIMEOUT must be greater than 0")
        validation_results["config_valid"] = False
    
    if API_RETRY_COUNT < 0:
        validation_results["errors"].append("API_RETRY_COUNT must be 0 or greater")
        validation_results["config_valid"] = False
    
    if FALLBACK_RETRY_LIMIT < 0:
        validation_results["errors"].append("FALLBACK_RETRY_LIMIT must be 0 or greater")
        validation_results["config_valid"] = False
    
    if FALLBACK_COOLDOWN_PERIOD < 0:
        validation_results["errors"].append("FALLBACK_COOLDOWN_PERIOD must be 0 or greater")
        validation_results["config_valid"] = False
    
    # Validate transcription method
    valid_methods = ["local", "api", "auto"]
    if DEFAULT_TRANSCRIPTION_METHOD not in valid_methods:
        validation_results["errors"].append(
            f"DEFAULT_TRANSCRIPTION_METHOD must be one of {valid_methods}, got '{DEFAULT_TRANSCRIPTION_METHOD}'"
        )
        validation_results["config_valid"] = False
    
    return validation_results