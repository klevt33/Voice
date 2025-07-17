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
from config import SAMPLE_RATE, CHUNK_SIZE, FORMAT, CHANNELS, SILENCE_THRESHOLD, SILENCE_DURATION, MAX_RECORDING_DURATION

# Configure logger for this module
logger = logging.getLogger(__name__)

# Calculate frames needed for silence duration
FRAMES_PER_BUFFER = int(SAMPLE_RATE * SILENCE_DURATION / CHUNK_SIZE)

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
    
    # Only process recordings that are substantial
    if len(frames) < 5:  # Ignore very short recordings
        logger.info(f"Discarding very short recording from {source} ({len(frames)} frames)")
        return
    
    logger.info(f"Processing new audio segment from {source} ({len(frames)} frames)")
    
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

def _wait_for_sound(stream, source: str, run_threads_ref: Dict[str, bool]) -> Optional[bytes]:
    """
    Waits for a consistent sound to be detected on the stream.

    Args:
        stream: The PyAudio stream to read from.
        source: The name of the audio source (e.g., "ME", "OTHERS").
        run_threads_ref: The shared dictionary to control thread execution.

    Returns:
        The first chunk of audio data that triggered the sound detection,
        or None if the thread is signaled to stop.
    """
    logger.debug(f"Waiting for sound on {source} microphone...")
    sound_counter = 0
    
    while run_threads_ref["active"] and run_threads_ref.get("listening", True):
        try:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            level = get_audio_level(data)
            
            if level > SILENCE_THRESHOLD:
                sound_counter += 1
                if sound_counter >= 2:  # Require at least 2 consecutive sound frames
                    logger.info(f"Sound detected on {source} microphone. Recording started.")
                    return data
            else:
                sound_counter = 0  # Reset counter if we detect silence
        except Exception as e:
            if run_threads_ref["active"]:
                logger.error(f"Error reading from {source} stream while waiting for sound: {e}")
                time.sleep(1)
    return None

def recording_thread(source: str, mic_data: Dict[str, Dict[str, Any]], 
                    audio_queue: queue.Queue, audio: pyaudio.PyAudio, 
                    run_threads_ref: Dict[str, bool]) -> None:
    """
    Generic thread for handling audio recording from a specific microphone.
    It waits for sound, records until silence, and then queues the audio for processing.
    """
    logger.info(f"Starting recording thread for {source}")
    
    mic = mic_data[source]
    mic_index = mic["index"]
    
    try:
        device_info = audio.get_device_info_by_index(mic_index)
        logger.info(f"Using {source} microphone: {device_info['name']} (index {mic_index})")
    except Exception as e:
        logger.error(f"Error accessing {source} microphone with index {mic_index}: {e}")
        return
    
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
    logger.info(f"Using silence threshold: {SILENCE_THRESHOLD}, silence duration: {SILENCE_DURATION}s ({FRAMES_PER_BUFFER} frames)")
    
    try:
        while run_threads_ref["active"]:
            if not run_threads_ref.get("listening", True):
                time.sleep(0.1)
                continue
            
            # 1. Wait for sound to begin
            initial_data = _wait_for_sound(stream, source, run_threads_ref)
            if not initial_data:
                continue # Loop will terminate if run_threads_ref['active'] is False

            mic["recording"] = True
            mic["frames"] = [initial_data]
            recording_start_time = time.time()  # Track recording start time
            max_duration_reached = False
            
            # 2. Record until silence is consistently detected or max duration reached
            silence_counter = 0
            consecutive_silence_required = FRAMES_PER_BUFFER
            
            while mic["recording"] and run_threads_ref["active"] and run_threads_ref.get("listening", True):
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    mic["frames"].append(data)
                    
                    # Check if maximum recording duration is exceeded
                    elapsed_time = time.time() - recording_start_time
                    if elapsed_time >= MAX_RECORDING_DURATION:
                        logger.info(f"Maximum recording duration ({MAX_RECORDING_DURATION}s) reached for {source} microphone. Completing current fragment.")
                        max_duration_reached = True
                        mic["recording"] = False
                        break
                    
                    level = get_audio_level(data)
                    if level <= SILENCE_THRESHOLD:
                        silence_counter += 1
                        if silence_counter >= consecutive_silence_required:
                            logger.info(f"Silence detected on {source} microphone for {SILENCE_DURATION}s. Recording stopped.")
                            mic["recording"] = False
                    else:
                        silence_counter = 0
                except Exception as e:
                    if run_threads_ref["active"]:
                        logger.error(f"Error during {source} recording: {e}")
            
            if not run_threads_ref.get("listening", True) and mic["recording"]:
                logger.info(f"Listening turned off while recording from {source}. Stopping recording.")
                mic["recording"] = False
            
            # 3. Process the recording
            if mic["frames"]:
                process_recording(mic["frames"], source, audio, audio_queue)
                mic["frames"] = []
            
            # 4. If max duration was reached, check if sound continues for new fragment
            if max_duration_reached and run_threads_ref["active"] and run_threads_ref.get("listening", True):
                try:
                    # Check current audio level to see if sound is still present
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    level = get_audio_level(data)
                    
                    if level > SILENCE_THRESHOLD:
                        logger.info(f"Sound continues after max duration reached on {source} microphone. Starting new fragment.")
                        # Continue the loop to start a new recording fragment
                        # The loop will restart from step 1, but we already have sound, so we can start recording immediately
                        mic["recording"] = True
                        mic["frames"] = [data]
                        recording_start_time = time.time()
                        max_duration_reached = False
                        
                        # Continue recording the new fragment
                        silence_counter = 0
                        while mic["recording"] and run_threads_ref["active"] and run_threads_ref.get("listening", True):
                            try:
                                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                                mic["frames"].append(data)
                                
                                # Check if maximum recording duration is exceeded again
                                elapsed_time = time.time() - recording_start_time
                                if elapsed_time >= MAX_RECORDING_DURATION:
                                    logger.info(f"Maximum recording duration ({MAX_RECORDING_DURATION}s) reached again for {source} microphone. Completing current fragment.")
                                    max_duration_reached = True
                                    mic["recording"] = False
                                    break
                                
                                level = get_audio_level(data)
                                if level <= SILENCE_THRESHOLD:
                                    silence_counter += 1
                                    if silence_counter >= consecutive_silence_required:
                                        logger.info(f"Silence detected on {source} microphone for {SILENCE_DURATION}s. Recording stopped.")
                                        mic["recording"] = False
                                else:
                                    silence_counter = 0
                            except Exception as e:
                                if run_threads_ref["active"]:
                                    logger.error(f"Error during {source} recording continuation: {e}")
                        
                        # Process the continuation fragment
                        if mic["frames"]:
                            process_recording(mic["frames"], source, audio, audio_queue)
                            mic["frames"] = []
                except Exception as e:
                    if run_threads_ref["active"]:
                        logger.error(f"Error checking for sound continuation on {source}: {e}")
    
    finally:
        logger.info(f"Cleaning up {source} recording thread")
        if stream:
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception as e:
                logger.error(f"Error closing {source} stream: {e}")