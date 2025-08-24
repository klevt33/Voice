#!/usr/bin/env python3
"""
Device Detection Integration Tests

This script tests the new dynamic audio device detection functionality.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import pyaudiowpatch as pyaudio
from audio_device_utils import (
    get_default_microphone_info, 
    get_default_speakers_loopback_info, 
    validate_device_info, 
    format_device_info
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_default_microphone_detection():
    """Test default microphone detection functionality"""
    print("\n=== Testing Default Microphone Detection ===")
    
    audio = pyaudio.PyAudio()
    try:
        device_info = get_default_microphone_info(audio)
        
        if device_info:
            print(f"✓ Default microphone detected: {format_device_info(device_info)}")
            
            # Validate the device
            if validate_device_info(device_info, "ME"):
                print("✓ Device validation passed")
                return True
            else:
                print("✗ Device validation failed")
                return False
        else:
            print("✗ No default microphone detected")
            return False
            
    except Exception as e:
        print(f"✗ Error during microphone detection: {e}")
        return False
    finally:
        audio.terminate()

def test_default_speakers_loopback_detection():
    """Test default speakers loopback detection functionality"""
    print("\n=== Testing Default Speakers Loopback Detection ===")
    
    audio = pyaudio.PyAudio()
    try:
        device_info = get_default_speakers_loopback_info(audio)
        
        if device_info:
            print(f"✓ Default speakers loopback detected: {format_device_info(device_info)}")
            
            # Validate the device
            if validate_device_info(device_info, "OTHERS"):
                print("✓ Device validation passed")
                return True
            else:
                print("✗ Device validation failed")
                return False
        else:
            print("✗ No default speakers loopback detected")
            print("  This may be normal if system doesn't support loopback audio")
            return False
            
    except Exception as e:
        print(f"✗ Error during speakers loopback detection: {e}")
        return False
    finally:
        audio.terminate()

def test_device_stream_creation():
    """Test creating audio streams with detected devices"""
    print("\n=== Testing Device Stream Creation ===")
    
    audio = pyaudio.PyAudio()
    success_count = 0
    
    try:
        # Test ME device stream creation
        me_device = get_default_microphone_info(audio)
        if me_device and validate_device_info(me_device, "ME"):
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
                
                # Test reading a chunk
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                stream.close()
                
                print(f"✓ ME device stream creation successful: {format_device_info(me_device)}")
                success_count += 1
                
            except Exception as e:
                print(f"✗ ME device stream creation failed: {e}")
        
        # Test OTHERS device stream creation
        others_device = get_default_speakers_loopback_info(audio)
        if others_device and validate_device_info(others_device, "OTHERS"):
            try:
                # Use updated channel logic - native channels for OTHERS
                channels = int(others_device["maxInputChannels"])
                sample_rate = int(others_device["defaultSampleRate"])
                
                stream = audio.open(
                    format=FORMAT,
                    channels=channels,
                    rate=sample_rate,
                    input=True,
                    input_device_index=others_device["index"],
                    frames_per_buffer=CHUNK_SIZE
                )
                
                # Test reading a chunk
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                stream.close()
                
                print(f"✓ OTHERS device stream creation successful: {format_device_info(others_device)}")
                success_count += 1
                
            except Exception as e:
                print(f"✗ OTHERS device stream creation failed: {e}")
        else:
            print("- OTHERS device not available for stream testing")
        
        return success_count > 0
        
    except Exception as e:
        print(f"✗ Error during stream creation testing: {e}")
        return False
    finally:
        audio.terminate()

def test_error_handling():
    """Test error handling for missing or invalid devices"""
    print("\n=== Testing Error Handling ===")
    
    # Test validation with None device
    if not validate_device_info(None, "TEST"):
        print("✓ None device validation correctly failed")
    else:
        print("✗ None device validation should have failed")
        return False
    
    # Test validation with invalid device info
    invalid_device = {"name": "Test", "index": 999}  # Missing required keys
    if not validate_device_info(invalid_device, "TEST"):
        print("✓ Invalid device validation correctly failed")
    else:
        print("✗ Invalid device validation should have failed")
        return False
    
    # Test format_device_info with None
    formatted = format_device_info(None)
    if formatted == "No device":
        print("✓ None device formatting handled correctly")
    else:
        print("✗ None device formatting failed")
        return False
    
    return True

def main():
    """Run all device detection integration tests"""
    print("=== Device Detection Integration Tests ===")
    print("Testing the new dynamic audio device detection functionality")
    
    tests = [
        ("Default Microphone Detection", test_default_microphone_detection),
        ("Default Speakers Loopback Detection", test_default_speakers_loopback_detection),
        ("Device Stream Creation", test_device_stream_creation),
        ("Error Handling", test_error_handling),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
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
        print("🎉 All tests passed!")
        return True
    else:
        print("❌ Some tests failed")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)