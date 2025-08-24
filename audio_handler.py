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

def _wait_for_sound(stream, source: str, run_threads_ref: Dict[str, bool], audio_monitor=None) -> Optional[List[bytes]]:
    """
    Waits for a consistent sound to be detected on the stream.

    Args:
        stream: The PyAudio stream to read from.
        source: The name of the audio source (e.g., "ME", "OTHERS").
        run_threads_ref: The shared dictionary to control thread execution.
        audio_monitor: Optional audio monitor for error handling.

    Returns:
        A list of audio chunks that should be included at the start of recording,
        or None if the thread is signaled to stop.
    """
    logger.debug(f"Waiting for sound on {source} microphone...")
    sound_counter = 0
    recent_chunks = []  # Rolling buffer to capture audio before detection
    max_buffer_size = 3  # Keep last 3 chunks (~70ms of audio)
    
    while run_threads_ref["active"] and run_threads_ref.get("listening", True):
        try:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            level = get_audio_level(data)
            
            # Maintain rolling buffer of recent chunks
            recent_chunks.append(data)
            if len(recent_chunks) > max_buffer_size:
                recent_chunks.pop(0)
            
            if level > SILENCE_THRESHOLD:
                sound_counter += 1
                if sound_counter >= 2:  # Require at least 2 consecutive sound frames
                    logger.info(f"Sound detected on {source} microphone. Recording started.")
                    # Return all chunks that should be included in the recording
                    # This includes the buffer chunks plus the current triggering chunk
                    return recent_chunks.copy()
            else:
                sound_counter = 0  # Reset counter if we detect silence
        except Exception as e:
            if run_threads_ref["active"]:
                logger.error(f"Error reading from {source} stream while waiting for sound: {e}")
                if audio_monitor:
                    audio_monitor.handle_audio_error(source, e)
                time.sleep(1)
    return None

def recording_thread(source: str, mic_data: Dict[str, Dict[str, Any]], 
                    audio_queue: queue.Queue, service_manager, 
                    run_threads_ref: Dict[str, bool], audio_monitor=None) -> None:
    """
    Generic thread for handling audio recording from a specific microphone.
    It waits for sound, records until silence, and then queues the audio for processing.
    """
    logger.info(f"Starting recording thread for {source}")
    
    mic = mic_data[source]
    mic_index = mic["index"]
    
    def get_current_audio():
        """Get the current PyAudio instance from service manager"""
        return service_manager.audio if service_manager else None
    
    def create_audio_stream():
        """Helper function to create audio stream with error handling"""
        current_audio = get_current_audio()
        if not current_audio:
            logger.error(f"No PyAudio instance available for {source}")
            return None
            
        try:
            # Get fresh device info each time
            device_info = current_audio.get_device_info_by_index(mic_index)
            logger.debug(f"Creating stream for {source} microphone: {device_info['name']} (index {mic_index})")
            
            stream = current_audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=mic_index,
                frames_per_buffer=CHUNK_SIZE
            )
            mic["stream"] = stream
            return stream
        except Exception as e:
            logger.error(f"Error opening {source} audio stream: {e}")
            if audio_monitor:
                audio_monitor.handle_audio_error(source, e)
            return None
    
    # Initial device info check
    try:
        current_audio = get_current_audio()
        if current_audio:
            device_info = current_audio.get_device_info_by_index(mic_index)
            logger.info(f"Starting {source} recording thread for: {device_info['name']} (index {mic_index})")
    except Exception as e:
        logger.error(f"Error accessing {source} microphone with index {mic_index}: {e}")
        return
    
    stream = create_audio_stream()
    if not stream:
        return
    
    logger.info(f"Ready to record from {source} microphone. Listening for sound...")
    logger.info(f"Using silence threshold: {SILENCE_THRESHOLD}, silence duration: {SILENCE_DURATION}s ({FRAMES_PER_BUFFER} frames)")
    
    try:
        while run_threads_ref["active"]:
            if not run_threads_ref.get("listening", True):
                time.sleep(0.1)
                continue
            
            # Check if stream is still valid, recreate if needed
            stream_needs_recreation = False
            if not stream or not hasattr(stream, 'is_active'):
                stream_needs_recreation = True
                logger.info(f"Stream object invalid for {source}, needs recreation")
            else:
                try:
                    # Test if the stream is actually usable by checking if it's active
                    if not stream.is_active():
                        stream_needs_recreation = True
                        logger.info(f"Stream not active for {source}, needs recreation")
                except Exception as e:
                    stream_needs_recreation = True
                    logger.info(f"Stream check failed for {source}, needs recreation: {e}")
            
            if stream_needs_recreation:
                logger.info(f"Recreating audio stream for {source}")
                # Clean up old stream if it exists
                if stream:
                    try:
                        if hasattr(stream, 'is_active') and stream.is_active():
                            stream.stop_stream()
                        stream.close()
                    except Exception as e:
                        logger.warning(f"Error cleaning up old stream for {source}: {e}")
                
                stream = create_audio_stream()
                if not stream:
                    logger.error(f"Failed to recreate audio stream for {source}, retrying in 5 seconds...")
                    time.sleep(5)
                    continue
            
            # 1. Wait for sound to begin
            try:
                initial_chunks = _wait_for_sound(stream, source, run_threads_ref, audio_monitor)
                if not initial_chunks:
                    continue # Loop will terminate if run_threads_ref['active'] is False
            except Exception as e:
                logger.error(f"Error waiting for sound on {source}: {e}")
                if audio_monitor:
                    audio_monitor.handle_audio_error(source, e)
                # Force stream recreation on next iteration
                stream = None
                time.sleep(1)
                continue

            mic["recording"] = True
            mic["frames"] = initial_chunks.copy()  # Start with all the initial chunks
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
                        if audio_monitor:
                            audio_monitor.handle_audio_error(source, e)
                        # Stop current recording and force stream recreation
                        mic["recording"] = False
                        stream = None
                        break
            
            if not run_threads_ref.get("listening", True) and mic["recording"]:
                logger.info(f"Listening turned off while recording from {source}. Stopping recording.")
                mic["recording"] = False
            
            # 3. Process the recording
            if mic["frames"]:
                current_audio = get_current_audio()
                if current_audio:
                    process_recording(mic["frames"], source, current_audio, audio_queue)
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
                                    if audio_monitor:
                                        audio_monitor.handle_audio_error(source, e)
                                    # Stop current recording and force stream recreation
                                    mic["recording"] = False
                                    stream = None
                                    break
                        
                        # Process the continuation fragment
                        if mic["frames"]:
                            current_audio = get_current_audio()
                            if current_audio:
                                process_recording(mic["frames"], source, current_audio, audio_queue)
                            mic["frames"] = []
                except Exception as e:
                    if run_threads_ref["active"]:
                        logger.error(f"Error checking for sound continuation on {source}: {e}")
                        if audio_monitor:
                            audio_monitor.handle_audio_error(source, e)
                        # Force stream recreation on next iteration
                        stream = None
    
    finally:
        logger.info(f"Cleaning up {source} recording thread")
        if stream:
            try:
                if hasattr(stream, 'is_active') and stream.is_active():
                    stream.stop_stream()
                if hasattr(stream, 'close'):
                    stream.close()
            except Exception as e:
                logger.error(f"Error closing {source} stream: {e}")
        # Clear the stream reference in mic_data
        if source in mic_data:
            mic_data[source]["stream"] = None