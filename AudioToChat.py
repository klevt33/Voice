import signal
import sys
import threading
import queue
import pyaudio
import time
import torch
import logging
from typing import Dict, List, Any, Optional
from config import (
    MIC_INDEX_ME, MIC_INDEX_OTHERS, CHAT, CHATS
)
from audio_handler import recording_thread, process_recording
from transcription import transcription_thread
from browser import get_chrome_driver, new_chat, load_prompt, browser_communication_thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("transcription.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Enable TF32 for better performance
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

# Global variables - use dictionary for reference passing
run_threads_ref = {"active": True}
audio: Optional[pyaudio.PyAudio] = None
audio_queue: queue.Queue = queue.Queue()  # Queue for in-memory audio data

# Dictionary to store thread-specific data
mic_data: Dict[str, Dict[str, Any]] = {
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

# Store all threads for proper cleanup
threads: List[threading.Thread] = []

def handle_exit(sig: Optional[int], frame: Optional[Any]) -> None:
    """Handle Ctrl+C by processing the current recording and exiting all threads"""
    global run_threads_ref, audio, threads
    logger.info("Ctrl+C detected. Processing last recordings and shutting down...")
    
    # Stop the global flag first
    run_threads_ref["active"] = False
    
    # Close all streams
    for source, data in mic_data.items():
        if data["stream"] is not None:
            try:
                if data["stream"].is_active():
                    data["stream"].stop_stream()
                data["stream"].close()
            except Exception as e:
                logger.error(f"Error closing stream for {source}: {e}")
        
        # Process any remaining recordings
        if data["recording"] and len(data["frames"]) > 0:
            try:
                if audio:
                    process_recording(data["frames"], source, audio, audio_queue)
            except Exception as e:
                logger.error(f"Error processing final recording for {source}: {e}")
    
    # Terminate PyAudio
    if audio:
        try:
            audio.terminate()
        except Exception as e:
            logger.error(f"Error terminating PyAudio: {e}")
    
    # Allow some time for threads to clean up
    logger.info("Waiting for threads to finish...")
    for thread in threads:
        try:
            thread.join(timeout=2)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} did not terminate gracefully")
        except Exception as e:
            logger.error(f"Error joining thread: {e}")
    
    logger.info("Exiting application")
    sys.exit(0)

def main() -> None:
    global run_threads_ref, threads, audio
    
    try:
        # Initialize browser
        driver = get_chrome_driver()
        if not driver:
            logger.error("Failed to initialize Chrome driver. Exiting.")
            return
        
        logger.info(f"Chrome session id: {driver.session_id}")
        
        # First, load the chat configurations with prompts
        chat_configs = load_prompt(CHATS)
        
        # Get the specific chat configuration we want to use
        active_chat_config = chat_configs.get(CHAT)
        if not active_chat_config:
            logger.error(f"Failed to load chat configuration for {CHAT}. Exiting.")
            return
        
        # Now initialize the chat with the loaded configuration
        final_chat_config = new_chat(driver, CHAT, active_chat_config)
        if not final_chat_config:
            logger.error("Failed to initialize chat. Exiting.")
            return
        
        # Initialize PyAudio
        audio = pyaudio.PyAudio()
        
        # Register signal handler
        signal.signal(signal.SIGINT, handle_exit)
            
        # Add a new queue for browser communication
        browser_queue = queue.Queue()
            
        # Create threads with names for better debugging
        recorder_me = threading.Thread(
            name="RecorderMe",
            target=recording_thread, 
            args=("ME", mic_data, audio_queue, audio, run_threads_ref)
        )
        recorder_me.daemon = True
        threads.append(recorder_me)
            
        recorder_others = threading.Thread(
            name="RecorderOthers",
            target=recording_thread, 
            args=("OTHERS", mic_data, audio_queue, audio, run_threads_ref)
        )
        recorder_others.daemon = True
        threads.append(recorder_others)
            
        transcriber = threading.Thread(
            name="Transcriber",
            target=transcription_thread, 
            args=(audio_queue, run_threads_ref, browser_queue)  # Changed parameters
        )
        transcriber.daemon = True
        threads.append(transcriber)
            
        # Add new browser communication thread
        browser_comm = threading.Thread(
            name="BrowserCommunication",
            target=browser_communication_thread,
            args=(browser_queue, run_threads_ref, final_chat_config)
        )
        browser_comm.daemon = True
        threads.append(browser_comm)
            
        # Start all threads
        for thread in threads:
            thread.start()
            logger.info(f"Started thread: {thread.name}")
            
        logger.info("All threads started. Press Ctrl+C to exit")
            
        # Keep the main thread alive until Ctrl+C
        try:
            while run_threads_ref["active"]:
                time.sleep(0.1)
        except KeyboardInterrupt:
            handle_exit(None, None)
            
    except Exception as e:
        logger.error(f"Error in main function: {e}", exc_info=True)
        handle_exit(None, None)

if __name__ == "__main__":
    main()