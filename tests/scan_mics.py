import pyaudio
import numpy as np
import time
import os

def detect_sound_from_mic(device_index=None, duration=5, threshold=50, rate=16000):
    """
    Test a specific microphone for sound input.
    
    Args:
        device_index: The index of the device to test (None for default device)
        duration: How long to listen for sound (seconds)
        threshold: Sound level threshold for detection
        rate: Sample rate to use
    
    Returns:
        Tuple of (bool, float) - detection success and sound level
    """
    p = pyaudio.PyAudio()
    
    try:
        # Get device info
        if device_index is not None:
            device_info = p.get_device_info_by_index(device_index)
            print(f"Testing device {device_index}: {device_info['name']}")
        else:
            device_info = p.get_default_input_device_info()
            device_index = device_info['index']
            print(f"Testing default device {device_index}: {device_info['name']}")
            
        # Try multiple sample rates if needed
        sample_rates = [16000, 44100, 48000, 8000]
        stream = None
        
        for rate in sample_rates:
            try:
                # Open stream
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    input=True,
                    frames_per_buffer=1024,
                    input_device_index=device_index
                )
                print(f"Successfully opened stream with sample rate {rate}")
                break  # Break if successful
            except Exception as e:
                print(f"Failed to open stream with rate {rate}: {e}")
                if rate == sample_rates[-1]:  # If this was the last rate
                    raise Exception("Could not open stream with any sample rate")
        
        if not stream:
            return False, 0
                
        print(f"Listening for {duration} seconds... Make some noise!")
        
        # Monitor sound levels
        max_level = 0
        detected = False
        start_time = time.time()
        
        while time.time() - start_time < duration:
            try:
                data = np.frombuffer(stream.read(1024, exception_on_overflow=False), dtype=np.int16)
                level = np.abs(data).mean()
                max_level = max(max_level, level)
                
                # Print current level to provide feedback
                print(f"Sound level: {level:.2f}", end="\r")
                
                if level > threshold:
                    detected = True
                    print(f"\nSound detected! Level: {level:.2f}")
                    # Don't break early - continue to find max level
            except Exception as e:
                print(f"\nError reading audio: {e}")
                break
                
        # Clean up
        stream.stop_stream()
        stream.close()
        
        return detected, max_level
        
    except Exception as e:
        print(f"Error setting up audio: {e}")
        return False, 0
    finally:
        p.terminate()

def list_all_devices():
    """List all audio devices with their indexes."""
    p = pyaudio.PyAudio()
    
    print("\n=== Available Audio Devices ===")
    print("Index\tInput Ch\tOutput Ch\tName")
    print("-" * 80)
    
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        name = dev_info.get('name', 'Unknown')
        input_ch = dev_info.get('maxInputChannels', 0)
        output_ch = dev_info.get('maxOutputChannels', 0)
        
        device_type = []
        if input_ch > 0:
            device_type.append("Input")
        if output_ch > 0:
            device_type.append("Output")
            
        print(f"{i}\t{input_ch}\t\t{output_ch}\t\t{name}")
    
    p.terminate()

def find_working_microphones():
    """Test all available microphones and return ones that work."""
    p = pyaudio.PyAudio()
    working_mics = []
    
    # First list all devices for reference
    list_all_devices()
    
    # Then try the default device
    print("\n--- Testing default microphone ---")
    default_index = None
    try:
        default_info = p.get_default_input_device_info()
        default_index = default_info['index']
    except Exception:
        print("No default input device available")
    
    if default_index is not None:
        detected, level = detect_sound_from_mic(default_index)
        result = {
            'index': default_index,
            'name': p.get_device_info_by_index(default_index)['name'],
            'level': level,
            'detected': detected
        }
        working_mics.append(result)
        if detected:
            print(f"\nDefault microphone detected sound! Index: {default_index}")
    
    # Now try Voicemeeter devices
    print("\n--- Looking for Voicemeeter devices ---")
    voicemeeter_terms = ['voicemeeter', 'vb-audio']
    
    voicemeeter_devices = []
    for i in range(p.get_device_count()):
        try:
            device_info = p.get_device_info_by_index(i)
            # Only include input devices not already tested
            if device_info['maxInputChannels'] <= 0 or i == default_index:
                continue
                
            name = device_info['name'].lower()
            
            # Check if this is a Voicemeeter device
            if any(term in name for term in voicemeeter_terms):
                voicemeeter_devices.append((i, device_info['name']))
        except Exception as e:
            print(f"Error checking device {i}: {e}")
    
    print(f"Found {len(voicemeeter_devices)} Voicemeeter input devices")
    
    # Test each Voicemeeter device
    for idx, name in voicemeeter_devices:
        print(f"\nTesting Voicemeeter device: {name} (Index: {idx})")
        try:
            detected, level = detect_sound_from_mic(idx, threshold=50)  # Lower threshold for virtual devices
            result = {
                'index': idx,
                'name': name,
                'level': level,
                'detected': detected
            }
            working_mics.append(result)
            if detected:
                print(f"Voicemeeter device detected sound! Index: {idx}")
        except Exception as e:
            print(f"Error testing device {idx}: {e}")
    
    # Sort by detection status and level
    working_mics.sort(key=lambda x: (not x['detected'], -x['level']))
    p.terminate()
    return working_mics

if __name__ == "__main__":
    print("=== Microphone Sound Detection ===")
    print("This script will test microphones for sound input.")
    
    # Clear screen for better visibility
    os.system('cls' if os.name == 'nt' else 'clear')
    
    results = find_working_microphones()
    
    print("\n=== Results ===")
    if not results:
        print("No working microphones found")
    else:
        for i, mic in enumerate(results):
            status = "✓ DETECTED SOUND" if mic['detected'] else "✗ No sound detected"
            print(f"{i+1}. [{status}] Index: {mic['index']} - {mic['name']} (Level: {mic['level']:.2f})")
        
        # Show the best microphone that detected sound
        best_mic = next((mic for mic in results if mic['detected']), None)
        if best_mic:
            print(f"\n✅ RECOMMENDED MICROPHONE: Index {best_mic['index']} - {best_mic['name']}")
        else:
            print("\nNo microphones detected sound during testing.")