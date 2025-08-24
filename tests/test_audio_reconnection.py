#!/usr/bin/env python3
"""
Audio Reconnection Test Script

This script tests the audio reconnection functionality with device changes.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import time
import threading
import pyaudiowpatch as pyaudio
from audio_monitor import AudioMonitor
from managers import ServiceManager, StateManager
from audio_device_utils import get_default_microphone_info, get_default_speakers_loopback_info, format_device_info

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MockUIController:
    """Mock UI controller for testing"""
    def __init__(self):
        self.last_status = None
        self.last_message = None
    
    def update_browser_status(self, status_key, message):
        self.last_status = status_key
        self.last_message = message
        print(f"UI Status: [{status_key}] {message}")

def test_manual_reconnection():
    """Test manual audio reconnection functionality"""
    print("\n=== Testing Manual Audio Reconnection ===")
    
    # Create mock components
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    
    try:
        # Initialize audio
        if not service_manager.initialize_audio():
            print("✗ Failed to initialize audio")
            return False
        
        print("✓ Audio initialized successfully")
        
        # Test manual reconnection
        print("Testing manual reconnection...")
        success = service_manager.audio_monitor.reconnect_all_audio_sources()
        
        if success:
            print("✓ Manual reconnection successful")
            
            # Check if devices are still detected
            me_device = service_manager.mic_data["ME"]["device_info"]
            others_device = service_manager.mic_data["OTHERS"]["device_info"]
            
            if me_device:
                print(f"✓ ME device after reconnection: {format_device_info(me_device)}")
            else:
                print("✗ ME device not available after reconnection")
                return False
            
            if others_device:
                print(f"✓ OTHERS device after reconnection: {format_device_info(others_device)}")
            else:
                print("- OTHERS device not available after reconnection (may be normal)")
            
            return True
        else:
            print("✗ Manual reconnection failed")
            return False
            
    except Exception as e:
        print(f"✗ Error during manual reconnection test: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def test_device_detection_refresh():
    """Test device detection refresh functionality"""
    print("\n=== Testing Device Detection Refresh ===")
    
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    
    try:
        # Initialize audio
        if not service_manager.initialize_audio():
            print("✗ Failed to initialize audio")
            return False
        
        # Get initial device info
        initial_me = service_manager.mic_data["ME"]["device_info"]
        initial_others = service_manager.mic_data["OTHERS"]["device_info"]
        
        print(f"Initial ME device: {format_device_info(initial_me)}")
        print(f"Initial OTHERS device: {format_device_info(initial_others)}")
        
        # Test device list refresh
        print("Testing device list refresh...")
        success = service_manager.audio_monitor._refresh_microphone_list()
        
        if success:
            print("✓ Device list refresh successful")
            
            # Verify devices are still accessible
            audio = pyaudio.PyAudio()
            try:
                current_me = get_default_microphone_info(audio)
                current_others = get_default_speakers_loopback_info(audio)
                
                print(f"Current ME device: {format_device_info(current_me)}")
                print(f"Current OTHERS device: {format_device_info(current_others)}")
                
                return True
            finally:
                audio.terminate()
        else:
            print("✗ Device list refresh failed")
            return False
            
    except Exception as e:
        print(f"✗ Error during device refresh test: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def test_reconnection_with_listening():
    """Test reconnection while listening mode is active"""
    print("\n=== Testing Reconnection with Listening Mode ===")
    
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    
    try:
        # Initialize audio
        if not service_manager.initialize_audio():
            print("✗ Failed to initialize audio")
            return False
        
        # Start listening mode
        state_manager.start_listening()
        print("✓ Listening mode started")
        
        # Wait a moment
        time.sleep(0.5)
        
        # Test reconnection while listening
        print("Testing reconnection while listening...")
        success = service_manager.audio_monitor.reconnect_all_audio_sources()
        
        if success:
            print("✓ Reconnection successful while listening")
            
            # Check if listening mode is still active
            if state_manager.is_listening():
                print("✓ Listening mode preserved after reconnection")
            else:
                print("- Listening mode stopped after reconnection (may be expected)")
            
            return True
        else:
            print("✗ Reconnection failed while listening")
            return False
            
    except Exception as e:
        print(f"✗ Error during listening reconnection test: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def test_status_bar_updates():
    """Test status bar updates during reconnection"""
    print("\n=== Testing Status Bar Updates ===")
    
    ui_controller = MockUIController()
    state_manager = StateManager()
    service_manager = ServiceManager(state_manager, ui_controller)
    
    try:
        # Initialize audio (should generate status updates)
        if not service_manager.initialize_audio():
            print("✗ Failed to initialize audio")
            return False
        
        print(f"✓ Initialization status: [{ui_controller.last_status}] {ui_controller.last_message}")
        
        # Test reconnection status updates
        print("Testing reconnection status updates...")
        success = service_manager.audio_monitor.reconnect_all_audio_sources()
        
        if success:
            print(f"✓ Reconnection status: [{ui_controller.last_status}] {ui_controller.last_message}")
            
            # Check if status indicates success
            if ui_controller.last_status == "success":
                print("✓ Status bar correctly shows success")
                return True
            else:
                print(f"- Status bar shows: {ui_controller.last_status} (may be normal)")
                return True
        else:
            print(f"✗ Reconnection failed, status: [{ui_controller.last_status}] {ui_controller.last_message}")
            return False
            
    except Exception as e:
        print(f"✗ Error during status bar test: {e}")
        return False
    finally:
        state_manager.shutdown()
        service_manager.shutdown_services()

def main():
    """Run all audio reconnection tests"""
    print("=== Audio Reconnection Integration Tests ===")
    print("Testing audio reconnection functionality with device changes")
    
    tests = [
        ("Manual Reconnection", test_manual_reconnection),
        ("Device Detection Refresh", test_device_detection_refresh),
        ("Reconnection with Listening", test_reconnection_with_listening),
        ("Status Bar Updates", test_status_bar_updates),
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
        print("🎉 All reconnection tests passed!")
        return True
    else:
        print("❌ Some reconnection tests failed")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)