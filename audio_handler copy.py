# audio_handler.py
import pyaudio
import numpy as np
import time
from datetime import datetime
import io
import wave
import queue
import logging
from typing import List, Dict, Any, Optional
from config import SAMPLE_RATE, CHUNK_SIZE, FORMAT, CHANNELS, SILENCE_THRESHOLD, FRAMES_PER_BUFFER

# Configure logger for this module
logger = logging.getLogger(__name__)

class AudioSegment:
    """Class to store audio data in memory"""
    def __init__(self, frames: List[bytes], sample_rate: int, channels: int, sample_width: int, source: str):
        self.frames = frames
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.source = source  # "ME" or "OTHERS" to identify the microphone source
    
    def get_wav_bytes(self) -> bytes:
        """Convert frames to WAV file bytes in memory using context managers"""
        wav_buffer = io.BytesIO()
        try:
            with wave.open(wav_buffer, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.sample_width)
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(self.frames))
            wav_buffer.seek(0)
            return wav_buffer.read()
        except Exception as e:
            logger.error(f"Error creating WAV data: {e}")
            # Return empty bytes if there's an error
            return b''

def get_audio_level(data: bytes) -> float:
    """Calculate the audio level using absolute values"""
    data_np = np.frombuffer(data, dtype=np.int16)
    return np.mean(np.abs(data_np))

def process_recording(frames: List[bytes], source: str, audio: pyaudio.PyAudio, 
                     audio_queue: queue.Queue) -> None:
    """Process the recorded frames and add to in-memory queue"""
    if not frames:
        logger.warning(f"No frames to process for {source}")
        return
    
    logger.info(f"Processing new audio segment from {source}")
    
    try:
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
        logger.info(f"Audio segment from {source} queued for transcription")
    except Exception as e:
        logger.error(f"Error processing recording from {source}: {e}")

def recording_thread(source: str, mic_data: Dict[str, Dict[str, Any]], 
                    audio_queue: queue.Queue, audio: pyaudio.PyAudio, 
                    run_threads_ref: Dict[str, bool]) -> None:
    """Generic thread for handling audio recording from a specific microphone"""
    logger.info(f"Starting recording thread for {source}")
    
    # Get the mic data for this source
    mic = mic_data[source]
    mic_index = mic["index"]
    
    # Get device info
    try:
        device_info = audio.get_device_info_by_index(mic_index)
        logger.info(f"Using {source} microphone: {device_info['name']} (index {mic_index})")
    except Exception as e:
        logger.error(f"Error accessing {source} microphone with index {mic_index}: {e}")
        return
    
    # Open the input stream
    stream = None
    try:
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=mic_index,
            frames_per_buffer=CHUNK_SIZE
        )
        mic["stream"] = stream
    except Exception as e:
        logger.error(f"Error opening {source} audio stream: {e}")
        return
    
    logger.info(f"Ready to record from {source} microphone. Listening for sound...")
    
    # Main recording loop
    try:
        while run_threads_ref["active"]:
            # Wait for sound to begin
            logger.debug(f"Waiting for sound on {source} microphone...")
            while run_threads_ref["active"]:
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    level = get_audio_level(data)
                    if level > SILENCE_THRESHOLD:
                        logger.info(f"Sound detected on {source} microphone. Recording started.")
                        mic["recording"] = True
                        mic["frames"] = [data]  # Start with the first chunk that triggered recording
                        break
                except Exception as e:
                    # Only print errors if we're still supposed to be running
                    if run_threads_ref["active"]:
                        logger.error(f"Error reading from {source} stream: {e}")
                        time.sleep(1)
                
                if not run_threads_ref["active"]:
                    break
            
            # Record until silence
            silence_counter = 0
            while mic["recording"] and run_threads_ref["active"]:
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    mic["frames"].append(data)
                    
                    # Check for silence
                    level = get_audio_level(data)
                    
                    if level <= SILENCE_THRESHOLD:
                        silence_counter += 1
                        if silence_counter >= FRAMES_PER_BUFFER:
                            logger.info(f"Silence detected on {source} microphone. Recording stopped.")
                            mic["recording"] = False
                    else:
                        silence_counter = 0
                except Exception as e:
                    # Only print errors if we're still supposed to be running
                    if run_threads_ref["active"]:
                        logger.error(f"Error during {source} recording: {e}")
            
            # Process the recording if we have data
            if mic["frames"] and len(mic["frames"]) > 0:
                process_recording(mic["frames"], source, audio, audio_queue)
                mic["frames"] = []
    
    finally:
        # Clean up - ensure stream is always properly closed
        logger.info(f"Cleaning up {source} recording thread")
        if stream:
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception as e:
                logger.error(f"Error closing {source} stream: {e}")