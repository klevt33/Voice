# config.py
import importlib.util
import os
import pyaudio

# DLL Paths
DLL_PATHS = [
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin",
    r"C:\Program Files\NVIDIA\CUDNN\v9.10\bin\12.9"
    # r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin",
    # r"C:\Program Files\NVIDIA\CUDNN\v8\bin"
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
WHISPER_MODEL = "large-v3"   # Whisper model to use. Options: "turbo" (fast, recommended), "large-v3" (slower, max accuracy)
# WHISPER_MODEL = "turbo"   # used on the other machine
COMPUTE_TYPE = "float16"  # Compute type (float16, int8)
LANGUAGE = "en"        # Set to English only
BEAM_SIZE = 5          # Beam size for faster-whisper

# Hot words: list of words/phrases to bias transcription toward specific spellings.
# These are joined with spaces and passed to faster-whisper's hotwords parameter.
# The model will favour these tokens in its output probability distribution.
# Set to [] to disable.
WHISPER_HOTWORDS: list[str] = [
    "Claude", "Claude Code", "Sonnet", "Opus", "Fable", "Astra", "Kirill", "Renee", "Logesh", "Sumit", "Pooja", "Vishal", "model-driven"
]

# Initial prompt: seeds the transcription context window to influence style and formatting.
# Useful for encouraging proper capitalization and punctuation in output.
# Set to None or "" to disable.
WHISPER_INITIAL_PROMPT: str | None = (
    "The following is a spoken transcript. Use proper capitalization and punctuation."
)

# --- Hallucination defenses -----------------------------------------------
# Non-speech audio (breathing, keyboard, background noise) makes Whisper —
# especially the turbo model — emit fluent but invented text. These layers
# stop noise before it reaches the decoder and filter what slips through.

# Silero VAD inside faster-whisper: strips non-speech audio before decoding.
WHISPER_VAD_ENABLED = True
WHISPER_VAD_PARAMETERS = {
    "threshold": 0.5,                  # speech probability cutoff
    "min_speech_duration_ms": 100,     # shorter speech chunks are discarded
    "min_silence_duration_ms": 500,    # silence shorter than this stays attached to speech
    "speech_pad_ms": 300,              # padding around detected speech
}
# Feed previously decoded text back as context. False prevents hallucination
# echo loops (one bad segment contaminating the next); our recordings are
# already per-utterance chunks so context adds little.
WHISPER_CONDITION_ON_PREV_TEXT = False
# Mild anti-repetition decoding pressure (kills "clip clip clip" loops).
WHISPER_REPETITION_PENALTY = 1.1
WHISPER_NO_REPEAT_NGRAM_SIZE = 3
# Word-level timestamps (needed for speaker splitting; small overhead).
WHISPER_WORD_TIMESTAMPS = False

# Client-side VAD gate: skips transcription entirely when a recorded segment
# contains less speech than SPEECH_GATE_MIN_SPEECH_S. Runs locally before any
# backend call, so it also protects the Groq API path. Auto-disabled if
# faster-whisper is not installed.
SPEECH_GATE_ENABLED = True
SPEECH_GATE_MIN_SPEECH_S = 0.4   # seconds of detected speech required
SPEECH_GATE_VAD_THRESHOLD = 0.5  # Silero speech probability cutoff

# Per-segment confidence post-filter (faster-whisper / Groq verbose_json
# segment metadata). A segment is dropped when any threshold is crossed.
SEG_NO_SPEECH_PROB_DROP = 0.6   # model thinks the segment is not speech
SEG_NO_SPEECH_LOGPROB = -0.6    # ... AND avg logprob below this → dropped
SEG_MIN_AVG_LOGPROB = -1.0      # very low-confidence decode (dropped alone)
SEG_MAX_COMPRESSION_RATIO = 2.4 # degenerate/repetitive output (dropped alone)

# --- Speaker separation (OTHERS channel) ------------------------------------
# Splits OTHERS audio containing multiple speakers into separate topics using
# client-side pyannote diarization. Requires: pyannote.audio==3.3.2 (pinned —
# 4.x needs torch>=2.8 and breaks the cu121 build; see SETUP_GUIDE.md),
# a HuggingFace account with accepted licenses for
# pyannote/speaker-diarization-3.1 and pyannote/segmentation-3.0, and the
# HF_TOKEN environment variable set to a read token (see SETUP_GUIDE.md).
SPEAKER_SPLIT_ENABLED = True
DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
DIARIZATION_MIN_TURN_S = 0.8    # speaker turns shorter than this merge into neighbours
DIARIZATION_MIN_SEGMENT_S = 2.0 # audio shorter than this skips diarization
HF_TOKEN_ENV_VAR = "HF_TOKEN"
# Clustering sensitivity for pyannote (default pipeline value ~0.70).
# Lower = more willing to declare a speaker change for similar voices
# (e.g. two men or two women); higher = fewer, more confident splits.
DIARIZATION_CLUSTERING_THRESHOLD = 0.4
# Diarization turn boundaries lag the true speech onset slightly, which
# drags a turn's first word ("I", "Oh") into the previous speaker's block.
# Shift turn starts earlier by this many seconds before aligning words.
DIARIZATION_BOUNDARY_SHIFT_S = 0.15
# After shifting, snap each turn boundary to the closest inter-word gap
# within this window (seconds) — splits land on natural pauses instead of
# cutting a turn's first word into the previous block.
DIARIZATION_BOUNDARY_SNAP_S = 0.35
# Minimum cluster size for speaker clustering (pipeline default ~15).
# Lower = short turns (quick answers ~1-2s) can be their own speaker;
# too low can fragment one speaker into many.
DIARIZATION_MIN_CLUSTER_SIZE = 5

# API Transcription Configuration
GROQ_API_KEY_ENV_VAR = "GROQ_API_KEY"  # Environment variable name for Groq API key
GROQ_MODEL = "whisper-large-v3"        # Groq Whisper model to use
API_REQUEST_TIMEOUT = 30.0             # Timeout for API requests in seconds
API_RETRY_COUNT = 3                    # Number of retry attempts for failed API requests
API_RETRY_BACKOFF = 2.0               # Exponential backoff multiplier for retries

# Transcription Method Configuration
DEFAULT_TRANSCRIPTION_METHOD = "auto"  # "local", "api", "auto", "network_gpu" (auto = prefer local GPU if available)
ENABLE_FALLBACK = True                 # Enable automatic fallback between transcription methods
FALLBACK_RETRY_LIMIT = 3              # Maximum number of fallback attempts before giving up
FALLBACK_COOLDOWN_PERIOD = 60.0       # Cooldown period in seconds before retrying failed method

# Network GPU Transcription Configuration
NETWORK_GPU_SERVER_URL = "http://192.168.1.231:8765"  # URL of the network GPU transcription server
NETWORK_GPU_TIMEOUT = 30.0                        # Timeout for network GPU requests in seconds
NETWORK_GPU_ENABLED = True                       # Enable network GPU transcription strategy
NETWORK_GPU_API_KEY = None                        # Optional Bearer token; None = auth disabled

# Shared Model Service Configuration
# When enabled, both the App and the Server probe localhost:MODEL_SERVICE_PORT at startup.
# Whichever starts first spawns ModelService as a subprocess; the second simply connects.
# This prevents double-loading the Whisper model into GPU memory.
MODEL_SERVICE_ENABLED = True                      # Enable shared ModelService spawn-or-connect
MODEL_SERVICE_PORT = 8766                         # Localhost port for ModelService
MODEL_SERVICE_STARTUP_TIMEOUT = 30.0              # Seconds to wait for ModelService to become healthy
MODEL_SERVICE_API_KEY = None                      # Optional Bearer token passed to ModelService; None = auth disabled
MODEL_SERVICE_URL = f"http://localhost:{MODEL_SERVICE_PORT}"  # Derived base URL

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
        "prompt_init_file": r"prompts\prompt_init_interview.txt",
        "prompt_msg_file": r"prompts\prompt_msg_interview.txt",
        "css_selector_input": "[id='ask-input']",
        "submit_button_selector": "button[aria-label='Submit']",
        "attach_files_button_selector": "button[aria-label='Add files or tools']",
        "file_input_selector_after_attach": "input[type='file']",
        "new_thread_button_selector": "a[aria-label='New']",
        "chat_response_selector": "[data-testid*='conversation-turn-'] .text-message",
        "generation_error_text": "Something went wrong"
    },
    "ChatGPT": {
        "url": "https://chatgpt.com/",
        "prompt_init_file": r"prompts\prompt_init_interview.txt", # Use a separate prompt for ChatGPT
        "prompt_msg_file": r"prompts\prompt_msg_interview.txt",   # and a separate message prompt
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

def is_pytorch_available():
    """Check if PyTorch is available"""
    return importlib.util.find_spec("torch") is not None

def is_faster_whisper_available():
    """Check if faster-whisper is available"""
    return importlib.util.find_spec("faster_whisper") is not None

def should_load_local_model():
    """Determine if local model should be loaded based on configuration and availability"""
    # Don't load local model if explicitly set to API only
    if DEFAULT_TRANSCRIPTION_METHOD == "api":
        return False
    
    # Don't load if PyTorch or faster-whisper not available
    if not is_pytorch_available() or not is_faster_whisper_available():
        return False
    
    # Load for "local" or "auto" modes when dependencies are available
    return DEFAULT_TRANSCRIPTION_METHOD in ["local", "auto"]

def validate_transcription_config():
    """Validate transcription configuration and return validation results"""
    validation_results = {
        "groq_api_available": is_groq_api_available(),
        "groq_api_key_configured": get_groq_api_key() is not None,
        "pytorch_available": is_pytorch_available(),
        "faster_whisper_available": is_faster_whisper_available(),
        "should_load_local_model": should_load_local_model(),
        "network_gpu_enabled": NETWORK_GPU_ENABLED,
        "network_gpu_server_url": NETWORK_GPU_SERVER_URL,
        "config_valid": True,
        "warnings": [],
        "errors": []
    }
    
    # Check PyTorch availability
    if not validation_results["pytorch_available"]:
        validation_results["warnings"].append(
            "PyTorch not available. Local GPU transcription will be unavailable."
        )
    
    # Check faster-whisper availability
    if not validation_results["faster_whisper_available"]:
        validation_results["warnings"].append(
            "faster-whisper not available. Local transcription will be unavailable."
        )
    
    # Check API configuration
    if not validation_results["groq_api_key_configured"]:
        validation_results["warnings"].append(
            f"Groq API key not found in environment variable '{GROQ_API_KEY_ENV_VAR}'. API transcription will be unavailable."
        )
    
    # Check if at least one transcription method is available
    has_local = validation_results["pytorch_available"] and validation_results["faster_whisper_available"]
    has_api = validation_results["groq_api_available"]
    
    if not has_local and not has_api:
        validation_results["errors"].append(
            "No transcription methods available. Install PyTorch + faster-whisper or configure Groq API key."
        )
        validation_results["config_valid"] = False
    
    # Validate configuration against available methods
    if DEFAULT_TRANSCRIPTION_METHOD == "local" and not has_local:
        validation_results["errors"].append(
            "DEFAULT_TRANSCRIPTION_METHOD is 'local' but local transcription is not available."
        )
        validation_results["config_valid"] = False
    
    if DEFAULT_TRANSCRIPTION_METHOD == "api" and not has_api:
        validation_results["errors"].append(
            "DEFAULT_TRANSCRIPTION_METHOD is 'api' but API transcription is not available."
        )
        validation_results["config_valid"] = False
    
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
    valid_methods = ["local", "api", "auto", "network_gpu"]
    if DEFAULT_TRANSCRIPTION_METHOD not in valid_methods:
        validation_results["errors"].append(
            f"DEFAULT_TRANSCRIPTION_METHOD must be one of {valid_methods}, got '{DEFAULT_TRANSCRIPTION_METHOD}'"
        )
        validation_results["config_valid"] = False

    # Validate network GPU configuration
    if NETWORK_GPU_ENABLED and not NETWORK_GPU_SERVER_URL:
        validation_results["errors"].append(
            "NETWORK_GPU_ENABLED is True but NETWORK_GPU_SERVER_URL is empty."
        )
        validation_results["config_valid"] = False

    if DEFAULT_TRANSCRIPTION_METHOD == "network_gpu" and not NETWORK_GPU_ENABLED:
        validation_results["warnings"].append(
            "DEFAULT_TRANSCRIPTION_METHOD is 'network_gpu' but NETWORK_GPU_ENABLED is False."
        )

    return validation_results