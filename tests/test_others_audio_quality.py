#!/usr/bin/env python3
"""
Standalone test script to capture OTHERS audio using the exact same logic as the main app
and play it back to verify audio quality.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyaudiowpatch as pyaudio
import numpy as np
import time
import wave
import logging
from typing import Dict, Any, Optional, List

# Import the exact same configuration and utilities as the main app
from config import SAMPLE_RATE, CHUNK_SIZE, FORMAT, CHANNELS, SILENCE_THRESHOLD, SILENCE_DURATION
from audio_device_utils import get_default_speakers_loopback_info, validate_device_info, format_device_info

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_audio_level(data: bytes) -> float:
    """Calculate the audio level using absolute values - same as main app"""
    data_np = np.frombuffer(data, dtype=np.int16)
    return np.mean(np.abs(data_np))

def wait_for_sound(stream, silence_threshold: float = SILENCE_THRESHOLD) -> Optional[List[bytes]]:
    """
    Wait for sound detection - simplified version of main app logic
    Returns initial chunks when sound is detected
    """
    logger.info("Waiting for sound...")
    sound_counter = 0
    recent_chunks = []
    max_buffer_size = 3
    
    while True:
        try:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            level = get_audio_level(data)
            
            # Maintain rolling buffer
            recent_chunks.append(data)
            if len(recent_chunks) > max_buffer_size:
                recent_chunks.pop(0)
            
            if level > silence_threshold:
                sound_counter += 1
                if sound_counter >= 2:  # Same as main app
                    logger.info(f"Sound detected! Level: {level:.1f}")
                    return recent_chunks.copy()
            else:
                sound_counter = 0
                
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            return None
        except Exception as e:
            logger.error(f"Error reading stream: {e}")
            return None

def record_until_silence(stream, initial_chunks: List[bytes], 
                        silence_threshold: float = SILENCE_THRESHOLD,
                        silence_duration: float = SILENCE_DURATION) -> List[bytes]:
    """
    Record until silence is detected - same logic as main app
    """
    frames = initial_chunks.copy()
    silence_counter = 0
    frames_per_buffer = int(SAMPLE_RATE * silence_duration / CHUNK_SIZE)
    
    logger.info(f"Recording... (silence threshold: {silence_threshold}, duration: {silence_duration}s)")
    
    while True:
        try:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            frames.append(data)
            
            level = get_audio_level(data)
            if level <= silence_threshold:
                silence_counter += 1
                if silence_counter >= frames_per_buffer:
                    logger.info(f"Silence detected for {silence_duration}s. Recording stopped.")
                    break
            else:
                silence_counter = 0
                
        except KeyboardInterrupt:
            logger.info("Recording interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error during recording: {e}")
            break
    
    logger.info(f"Recorded {len(frames)} chunks")
    return frames

def save_audio(frames: List[bytes], channels: int, sample_rate: int, 
               sample_width: int, filename: str = "others_test_recording.wav"):
    """Save recorded audio to WAV file"""
    try:
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(b''.join(frames))
        logger.info(f"Audio saved to {filename}")
        return True
    except Exception as e:
        logger.error(f"Error saving audio: {e}")
        return False

def play_audio(filename: str = "others_test_recording.wav"):
    """Play back the recorded audio"""
    try:
        with wave.open(filename, 'rb') as wf:
            # Get audio parameters
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frames = wf.getnframes()
            
            logger.info(f"Playing back: {channels} channels, {sample_rate} Hz, {frames} frames")
            
            # Create PyAudio instance for playback
            p = pyaudio.PyAudio()
            
            # Open playback stream
            stream = p.open(
                format=p.get_format_from_width(sample_width),
                channels=channels,
                rate=sample_rate,
                output=True
            )
            
            # Read and play audio in chunks
            chunk_size = 1024
            data = wf.readframes(chunk_size)
            
            while data:
                stream.write(data)
                data = wf.readframes(chunk_size)
            
            # Cleanup
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            logger.info("Playback completed")
            return True
            
    except Exception as e:
        logger.error(f"Error playing audio: {e}")
        return False

def test_others_audio_capture():
    """
    Main test function that captures OTHERS audio using exact same logic as main app
    """
    logger.info("=== OTHERS Audio Quality Test ===")
    logger.info("This test uses the exact same logic as the main application")
    
    # Create PyAudio instance
    audio = pyaudio.PyAudio()
    
    try:
        # Get OTHERS device info using same logic as test_loopback.py
        logger.info("Detecting OTHERS audio device...")
        
        # Get default output device info (same as test_loopback.py)
        default_speakers = audio.get_device_info_by_index(
            audio.get_default_output_device_info()['index']
        )
        
        # Find the corresponding loopback device (same as test_loopback.py)
        if not default_speakers["isLoopbackDevice"]:
            for loopback in audio.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    default_speakers = loopback
                    break
            else:
                logger.error("Default loopback output device not found.")
                return False
        
        device_info = default_speakers
        
        logger.info(f"Using device: {device_info['name']} (index {device_info['index']})")
        
        # Use device's native settings (exactly like test_loopback.py)
        channels = int(device_info["maxInputChannels"])
        sample_rate = int(device_info["defaultSampleRate"])
        
        logger.info(f"Recording from: {device_info['name']}")
        logger.info(f"Channels: {channels}, Sample Rate: {sample_rate} Hz")
        
        # Create stream with same parameters as main app
        stream = audio.open(
            format=FORMAT,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device_info["index"],
            frames_per_buffer=CHUNK_SIZE
        )
        
        logger.info("Stream created successfully")
        logger.info("Play some audio on your system and speak/make noise...")
        logger.info("Press Ctrl+C to stop the test")
        
        # Wait for sound using same logic as main app
        initial_chunks = wait_for_sound(stream)
        if not initial_chunks:
            logger.info("No sound detected or test interrupted")
            return False
        
        # Record until silence using same logic as main app
        all_frames = record_until_silence(stream, initial_chunks)
        
        # Clean up stream
        stream.stop_stream()
        stream.close()
        
        if not all_frames:
            logger.warning("No audio recorded")
            return False
        
        # Save audio using same format as main app
        sample_width = audio.get_sample_size(FORMAT)
        success = save_audio(all_frames, channels, sample_rate, sample_width)
        
        if success:
            logger.info("\n=== Playing back recorded audio ===")
            time.sleep(1)  # Brief pause
            play_audio()
            
            logger.info("\n=== Test Summary ===")
            logger.info(f"Device: {device_info['name']}")
            logger.info(f"Channels: {channels} (using device native channels)")
            logger.info(f"Sample Rate: {sample_rate} Hz")
            logger.info(f"Recorded chunks: {len(all_frames)}")
            logger.info("Audio file: others_test_recording.wav")
            logger.info("✅ Now using device's native channel count for better audio quality!")
        
        return success
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False
    finally:
        audio.terminate()

if __name__ == "__main__":
    try:
        success = test_others_audio_capture()
        if success:
            print("\n✅ Test completed successfully!")
            print("Check the audio quality of 'others_test_recording.wav'")
        else:
            print("\n❌ Test failed!")
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")