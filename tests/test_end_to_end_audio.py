#!/usr/bin/env python3
"""
End-to-End Audio Capture Test

This script validates the complete audio capture pipeline with the new dynamic device detection.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import time
import threading
import queue
import pyaudiowpatch as pyaudio
from audio_handler import AudioSegment, recording_thread, process_recording
from audio_device_utils import get_default_microphone_info, get_default_speakers_loopback_info, format_device_info
from managers import ServiceManager, StateManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MockUIController:
    """Mock UI controller for testing"""
    def update_browser_status(self, status_key, message):
        print(f"UI Status: [{status_key}] {message}")

def test_audio_segment_creation():
    """Test AudioSegment creation with dynamic device parameters"""
    print("\n=== Testing AudioSegment Creation ===")
    
    audio = pyaudio.PyAudio()
    try:
        # Get device info
        me_device = get_default_microphone_info(audio)
        if not me_device:
            print("✗ No ME device available for testing")
            return False
        
        print(f"Testing with device: {format_device_info(me_device)}")
        
        # Create test frames
        test_frames = [b'\x00' * 1024 for _ in range(10)]  # 10 frames of silence
        
        # Create AudioSegment with device-specific parameters
        sample_rate = int(me_device["defaultSampleRate"])
        channels = min(int(me_device["maxInputChannels"]), 2)
        
        audio_segment = AudioSegment(
            frames=test_frames,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=audio.get_sample_size(pyaudio.paInt16),
            source="ME"
        )
        
        # Test WAV conversion
        wav_data = audio_segment.get_wav_bytes()
        if wav_data:
            print(f"✓ AudioSegment created successfully")
            print(f"  Sample rate: {audio_segment.sample_rate}")
            print(f"  Channels: {audio_segment.channels}")
            print(f"  WAV data size: {len(wav_data)} bytes")
            return True
        else:
            print("✗ Failed to generate WAV data")
            return False
            
    except Exception as e:
        print(f"✗ Error creating AudioSegment: {e}")
        return False
    finally:
        audio.terminate()

def test_process_recording_with_device_info():
    """Test process_recording function with device info"""
    print("\n=== Testing process_recording with Device Info ===")
    
    audio = pyaudio.PyAudio()
    audio_queue = queue.Queue()
    
    try:
        # Get device info
        me_device = get_default_microphone_info(audio)
        if not me_device:
            print("✗ No ME device available for testing")
            return False
        
        # Create test frames
        test_frames = [b'\x00' * 1024 for _ in range(20)]  # 20 frames
        
        # Process recording with device info
        process_recording(test_frames, "ME", audio, audio_queue, me_device)
        
        # Check if audio segment was queued
        if not audio_queue.empty():
            audio_segment = audio_queue.get()
            print(f"✓ Audio segment processed successfully")
            print(f"  Source: {audio_segment.source}")
            print(f"  Sample rate: {audio_segment.sample_rate}")
            print(f"  Channels: {audio_segment.channels}")
            print(f"  Frames: {len(audio_segment.frames)}")
            return True
        else:
            print("✗ No audio segment was queued")
            return False
            
    except Exception as e:
        print(f"✗ Error processing recording: {e}")
        return False
    finally:
        audio.terminate()

def test_service_manager_initialization():
    """Test ServiceManager initialization with dynamic device detection"""
    print("\n=== Testing ServiceManager Initialization ===")
    
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    
    try:
        # Test audio initialization
        success = service_manager.initialize_audio()
        
        if success:
            print("✓ ServiceManager audio initialization successful")
            
            # Check device info
            me_device = service_manager.mic_data["ME"]["device_info"]
            others_device = service_manager.mic_data["OTHERS"]["device_info"]
            
            if me_device:
                print(f"✓ ME device detected: {format_device_info(me_device)}")
            else:
                print("✗ ME device not detected")
                return False
            
            if others_device:
                print(f"✓ OTHERS device detected: {format_device_info(others_device)}")
            else:
                print("- OTHERS device not detected (may be normal)")
            
            return True
        else:
            print("✗ ServiceManager audio initialization failed")
            return False
            
    except Exception as e:
        print(f"✗ Error during ServiceManager initialization: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def test_recording_thread_startup():
    """Test recording thread startup with dynamic device detection"""
    print("\n=== Testing Recording Thread Startup ===")
    
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    audio_queue = queue.Queue()
    
    try:
        # Initialize audio
        if not service_manager.initialize_audio():
            print("✗ Failed to initialize audio")
            return False
        
        # Test ME recording thread startup
        print("Testing ME recording thread startup...")
        
        # Create a thread that will run briefly
        run_threads_ref = {"active": True, "listening": False}  # Not listening to avoid actual recording
        
        me_thread = threading.Thread(
            target=recording_thread,
            args=("ME", service_manager.mic_data, audio_queue, service_manager, run_threads_ref, service_manager.audio_monitor)
        )
        me_thread.daemon = True
        me_thread.start()
        
        # Let it initialize
        time.sleep(1)
        
        # Stop the thread
        run_threads_ref["active"] = False
        me_thread.join(timeout=5)
        
        if not me_thread.is_alive():
            print("✓ ME recording thread started and stopped successfully")
            
            # Test OTHERS if available
            others_device = service_manager.mic_data["OTHERS"]["device_info"]
            if others_device:
                print("Testing OTHERS recording thread startup...")
                
                run_threads_ref = {"active": True, "listening": False}
                
                others_thread = threading.Thread(
                    target=recording_thread,
                    args=("OTHERS", service_manager.mic_data, audio_queue, service_manager, run_threads_ref, service_manager.audio_monitor)
                )
                others_thread.daemon = True
                others_thread.start()
                
                time.sleep(1)
                run_threads_ref["active"] = False
                others_thread.join(timeout=5)
                
                if not others_thread.is_alive():
                    print("✓ OTHERS recording thread started and stopped successfully")
                else:
                    print("✗ OTHERS recording thread did not stop properly")
                    return False
            
            return True
        else:
            print("✗ ME recording thread did not stop properly")
            return False
            
    except Exception as e:
        print(f"✗ Error during recording thread test: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def test_audio_pipeline_integrity():
    """Test the complete audio processing pipeline"""
    print("\n=== Testing Audio Pipeline Integrity ===")
    
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    audio_queue = queue.Queue()
    
    try:
        # Initialize audio
        if not service_manager.initialize_audio():
            print("✗ Failed to initialize audio")
            return False
        
        # Test pipeline components
        print("Testing pipeline components...")
        
        # 1. Device detection
        me_device = service_manager.mic_data["ME"]["device_info"]
        if not me_device:
            print("✗ ME device not available")
            return False
        
        # 2. Stream creation simulation
        audio = pyaudio.PyAudio()
        try:
            from config import FORMAT, CHUNK_SIZE
            
            # Use updated channel logic
            channels = min(int(me_device["maxInputChannels"]), 2)
            sample_rate = int(me_device["defaultSampleRate"])
            
            stream = audio.open(
                format=FORMAT,
                channels=channels,
                rate=sample_rate,
                input=True,
                input_device_index=me_device["index"],
                frames_per_buffer=CHUNK_SIZE
            )
            
            # 3. Audio capture simulation
            test_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            stream.close()
            
            # 4. Audio processing
            test_frames = [test_data] * 10  # Simulate multiple frames
            process_recording(test_frames, "ME", audio, audio_queue, me_device)
            
            # 5. Queue verification
            if not audio_queue.empty():
                audio_segment = audio_queue.get()
                print("✓ Complete audio pipeline test successful")
                print(f"  Captured {len(audio_segment.frames)} frames")
                print(f"  Sample rate: {audio_segment.sample_rate}")
                print(f"  Channels: {audio_segment.channels}")
                return True
            else:
                print("✗ Audio segment not queued properly")
                return False
                
        finally:
            audio.terminate()
            
    except Exception as e:
        print(f"✗ Error during pipeline integrity test: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def main():
    """Run all end-to-end audio capture tests"""
    print("=== End-to-End Audio Capture Tests ===")
    print("Validating complete audio capture functionality with dynamic device detection")
    
    tests = [
        ("AudioSegment Creation", test_audio_segment_creation),
        ("process_recording with Device Info", test_process_recording_with_device_info),
        ("ServiceManager Initialization", test_service_manager_initialization),
        ("Recording Thread Startup", test_recording_thread_startup),
        ("Audio Pipeline Integrity", test_audio_pipeline_integrity),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            print(f"\n--- {test_name} ---")
            if test_func():
                passed += 1
                print(f"✓ {test_name}: PASSED")
            else:
                print(f"✗ {test_name}: FAILED")
        except Exception as e:
            print(f"✗ {test_name}: ERROR - {e}")
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {passed}/{total}")
    print(f"Success Rate: {100*passed/total:.1f}%")
    
    if passed == total:
        print("🎉 All end-to-end tests passed!")
        print("The audio capture system is working correctly with dynamic device detection.")
        return True
    else:
        print("❌ Some end-to-end tests failed")
        print("Please check the audio system configuration.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)