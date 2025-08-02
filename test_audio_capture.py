#!/usr/bin/env python3
"""
Audio Capture Test Script

This script tests the audio capture functionality from audio_handler.py
It can save captured audio to files and optionally play them back for quality testing.
"""

import os
import sys
import time
import threading
import queue
import pyaudio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

# Import from your existing modules
from audio_handler import AudioSegment, get_audio_level, _wait_for_sound, process_recording
from config import (
    SAMPLE_RATE, CHUNK_SIZE, FORMAT, CHANNELS, 
    SILENCE_THRESHOLD, SILENCE_DURATION, MAX_RECORDING_DURATION,
    MIC_INDEX_ME, MIC_INDEX_OTHERS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AudioTester:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.audio_queue = queue.Queue()
        self.run_threads = {"active": True, "listening": True}
        self.test_recordings_dir = "test_recordings"
        
        # Create test recordings directory
        os.makedirs(self.test_recordings_dir, exist_ok=True)
        
        # Available microphones
        self.available_mics = {
            "ME": {"index": MIC_INDEX_ME, "stream": None, "recording": False, "frames": []},
            "OTHERS": {"index": MIC_INDEX_OTHERS, "stream": None, "recording": False, "frames": []}
        }
        
        logger.info(f"Test recordings will be saved to: {os.path.abspath(self.test_recordings_dir)}")
    
    def list_audio_devices(self):
        """List all available audio input devices"""
        print("\n=== Available Audio Devices ===")
        device_count = self.audio.get_device_count()
        
        for i in range(device_count):
            try:
                device_info = self.audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:  # Only show input devices
                    status = ""
                    if i == MIC_INDEX_ME:
                        status = " (configured as ME mic)"
                    elif i == MIC_INDEX_OTHERS:
                        status = " (configured as OTHERS mic)"
                    
                    print(f"  {i}: {device_info['name']}{status}")
                    print(f"      Max input channels: {device_info['maxInputChannels']}")
                    print(f"      Default sample rate: {device_info['defaultSampleRate']}")
            except Exception as e:
                print(f"  {i}: Error getting device info - {e}")
        print()
    
    def test_audio_levels(self, mic_source: str = "ME", duration: int = 10):
        """Monitor audio levels in real-time without recording"""
        print(f"\n=== Testing Audio Levels for {mic_source} microphone ===")
        print(f"Monitoring for {duration} seconds...")
        print(f"Silence threshold: {SILENCE_THRESHOLD}")
        print("Press Ctrl+C to stop early\n")
        
        mic_index = self.available_mics[mic_source]["index"]
        
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=mic_index,
                frames_per_buffer=CHUNK_SIZE
            )
            
            start_time = time.time()
            max_level = 0
            samples_above_threshold = 0
            total_samples = 0
            
            while time.time() - start_time < duration:
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    level = get_audio_level(data)
                    max_level = max(max_level, level)
                    total_samples += 1
                    
                    if level > SILENCE_THRESHOLD:
                        samples_above_threshold += 1
                        status = "SOUND"
                    else:
                        status = "silence"
                    
                    # Update every 0.1 seconds
                    print(f"\rLevel: {level:6.1f} | Max: {max_level:6.1f} | Status: {status:7s} | Active: {samples_above_threshold}/{total_samples}", end="", flush=True)
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"Error reading audio: {e}")
            
            stream.close()
            print(f"\n\nTest completed!")
            print(f"Maximum level detected: {max_level:.1f}")
            print(f"Samples above threshold: {samples_above_threshold}/{total_samples} ({100*samples_above_threshold/total_samples:.1f}%)")
            
        except Exception as e:
            logger.error(f"Error opening audio stream for {mic_source}: {e}")
    
    def single_capture_test(self, mic_source: str = "ME", save_file: bool = True, play_back: bool = False):
        """Capture a single audio segment and optionally save/play it"""
        print(f"\n=== Single Capture Test for {mic_source} microphone ===")
        print("Waiting for sound to start recording...")
        print("Speak into the microphone or make some noise...")
        
        mic_data = {mic_source: self.available_mics[mic_source].copy()}
        
        # Start a recording thread
        recording_thread = threading.Thread(
            target=self._single_recording_worker,
            args=(mic_source, mic_data, save_file, play_back)
        )
        recording_thread.start()
        
        try:
            recording_thread.join()
        except KeyboardInterrupt:
            print("\nStopping capture...")
            self.run_threads["active"] = False
            recording_thread.join()
    
    def _single_recording_worker(self, source: str, mic_data: Dict[str, Dict[str, Any]], 
                                save_file: bool, play_back: bool):
        """Worker thread for single recording capture"""
        mic = mic_data[source]
        mic_index = mic["index"]
        
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=mic_index,
                frames_per_buffer=CHUNK_SIZE
            )
            
            # Wait for sound
            initial_data = _wait_for_sound(stream, source, self.run_threads)
            if not initial_data:
                print("No sound detected or interrupted")
                return
            
            # Record until silence
            frames = [initial_data]
            silence_counter = 0
            frames_per_buffer = int(SAMPLE_RATE * SILENCE_DURATION / CHUNK_SIZE)
            recording_start = time.time()
            
            print("Recording... (speak now)")
            
            while self.run_threads["active"]:
                try:
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    frames.append(data)
                    
                    # Check for max duration
                    if time.time() - recording_start >= MAX_RECORDING_DURATION:
                        print(f"Maximum recording duration ({MAX_RECORDING_DURATION}s) reached")
                        break
                    
                    level = get_audio_level(data)
                    if level <= SILENCE_THRESHOLD:
                        silence_counter += 1
                        if silence_counter >= frames_per_buffer:
                            print(f"Silence detected for {SILENCE_DURATION}s. Recording stopped.")
                            break
                    else:
                        silence_counter = 0
                        
                except Exception as e:
                    logger.error(f"Error during recording: {e}")
                    break
            
            stream.close()
            
            if frames:
                duration = len(frames) * CHUNK_SIZE / SAMPLE_RATE
                print(f"Recorded {len(frames)} frames ({duration:.2f} seconds)")
                
                # Create AudioSegment
                audio_segment = AudioSegment(
                    frames=frames,
                    sample_rate=SAMPLE_RATE,
                    channels=CHANNELS,
                    sample_width=self.audio.get_sample_size(FORMAT),
                    source=source
                )
                
                if save_file:
                    self._save_audio_segment(audio_segment)
                
                if play_back:
                    self._play_audio_segment(audio_segment)
            else:
                print("No audio data captured")
                
        except Exception as e:
            logger.error(f"Error in recording worker: {e}")
    
    def _save_audio_segment(self, audio_segment: AudioSegment):
        """Save an audio segment to a WAV file"""
        filename = f"{audio_segment.source}_{audio_segment.timestamp}.wav"
        filepath = os.path.join(self.test_recordings_dir, filename)
        
        try:
            wav_data = audio_segment.get_wav_bytes()
            if wav_data:
                with open(filepath, 'wb') as f:
                    f.write(wav_data)
                print(f"Audio saved to: {filepath}")
            else:
                print("Failed to generate WAV data")
        except Exception as e:
            logger.error(f"Error saving audio: {e}")
    
    def _play_audio_segment(self, audio_segment: AudioSegment):
        """Play back an audio segment"""
        print("Playing back recorded audio...")
        
        try:
            # Create playback stream
            stream = self.audio.open(
                format=FORMAT,
                channels=audio_segment.channels,
                rate=audio_segment.sample_rate,
                output=True
            )
            
            # Play the frames
            for frame in audio_segment.frames:
                stream.write(frame)
            
            stream.close()
            print("Playback completed")
            
        except Exception as e:
            logger.error(f"Error during playback: {e}")
    
    def continuous_monitoring_test(self, mic_source: str = "ME", duration: int = 60):
        """Continuously monitor and save audio segments like the main application"""
        print(f"\n=== Continuous Monitoring Test for {mic_source} microphone ===")
        print(f"Monitoring for {duration} seconds...")
        print("Each detected audio segment will be saved as a separate file")
        print("Press Ctrl+C to stop early\n")
        
        # Queue processor thread
        processor_thread = threading.Thread(target=self._queue_processor)
        processor_thread.start()
        
        # Recording thread
        mic_data = {mic_source: self.available_mics[mic_source].copy()}
        recording_thread = threading.Thread(
            target=self._continuous_recording_worker,
            args=(mic_source, mic_data, duration)
        )
        recording_thread.start()
        
        try:
            recording_thread.join()
        except KeyboardInterrupt:
            print("\nStopping monitoring...")
        finally:
            self.run_threads["active"] = False
            processor_thread.join()
    
    def _continuous_recording_worker(self, source: str, mic_data: Dict[str, Dict[str, Any]], duration: int):
        """Worker for continuous recording like the main app"""
        from audio_handler import recording_thread
        
        # Set a timer to stop after duration
        def stop_after_duration():
            time.sleep(duration)
            self.run_threads["active"] = False
        
        timer_thread = threading.Thread(target=stop_after_duration)
        timer_thread.start()
        
        # Use the actual recording thread from audio_handler
        recording_thread(source, mic_data, self.audio_queue, self.audio, self.run_threads)
        
        timer_thread.join()
    
    def _queue_processor(self):
        """Process audio segments from the queue"""
        segment_count = 0
        
        while self.run_threads["active"] or not self.audio_queue.empty():
            try:
                audio_segment = self.audio_queue.get(timeout=1)
                segment_count += 1
                
                print(f"Processing segment #{segment_count} from {audio_segment.source}")
                self._save_audio_segment(audio_segment)
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing audio segment: {e}")
        
        print(f"\nProcessed {segment_count} audio segments total")
    
    def cleanup(self):
        """Clean up resources"""
        self.run_threads["active"] = False
        self.audio.terminate()

def main():
    print("=== Audio Capture Test Script ===")
    print("This script tests the audio capture functionality from your audio_handler.py")
    
    tester = AudioTester()
    
    try:
        while True:
            print("\nSelect a test mode:")
            print("1. List audio devices")
            print("2. Test audio levels (real-time monitoring)")
            print("3. Single capture test (record one segment)")
            print("4. Continuous monitoring test (like main app)")
            print("5. Exit")
            
            choice = input("\nEnter your choice (1-5): ").strip()
            
            if choice == "1":
                tester.list_audio_devices()
            
            elif choice == "2":
                mic = input("Test which microphone? (ME/OTHERS) [ME]: ").strip().upper() or "ME"
                if mic not in ["ME", "OTHERS"]:
                    print("Invalid choice. Using ME.")
                    mic = "ME"
                duration = input("Duration in seconds [10]: ").strip()
                try:
                    duration = int(duration) if duration else 10
                except ValueError:
                    duration = 10
                tester.test_audio_levels(mic, duration)
            
            elif choice == "3":
                mic = input("Test which microphone? (ME/OTHERS) [ME]: ").strip().upper() or "ME"
                if mic not in ["ME", "OTHERS"]:
                    print("Invalid choice. Using ME.")
                    mic = "ME"
                save = input("Save to file? (y/n) [y]: ").strip().lower()
                save_file = save != "n"
                play = input("Play back after recording? (y/n) [n]: ").strip().lower()
                play_back = play == "y"
                tester.single_capture_test(mic, save_file, play_back)
            
            elif choice == "4":
                mic = input("Test which microphone? (ME/OTHERS) [ME]: ").strip().upper() or "ME"
                if mic not in ["ME", "OTHERS"]:
                    print("Invalid choice. Using ME.")
                    mic = "ME"
                duration = input("Duration in seconds [60]: ").strip()
                try:
                    duration = int(duration) if duration else 60
                except ValueError:
                    duration = 60
                tester.continuous_monitoring_test(mic, duration)
            
            elif choice == "5":
                break
            
            else:
                print("Invalid choice. Please try again.")
    
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        tester.cleanup()

if __name__ == "__main__":
    main()