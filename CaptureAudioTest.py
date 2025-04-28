import pyaudio
import wave
import numpy as np
import time
from datetime import datetime
import signal
import sys
import os

# Configuration variables
MIC_INDEX = 8          # Voicemeeter Out B1 index
SAMPLE_RATE = 44100    # Audio sampling rate
CHUNK_SIZE = 1024      # Buffer size for processing
FORMAT = pyaudio.paInt16  # Audio format
CHANNELS = 1           # Mono audio
SILENCE_THRESHOLD = 100  # Threshold for Voicemeeter
SILENCE_DURATION = 1.0   # Duration of silence to stop recording (in seconds)
FRAMES_PER_BUFFER = int(SAMPLE_RATE * SILENCE_DURATION / CHUNK_SIZE)  # Calculate frames needed for silence duration
RECORDINGS_FOLDER = "recordings"  # Folder to save recordings in

# Global variables for signal handling
recording = False
audio = None
frames = []

def handle_exit(sig, frame):
    """Handle Ctrl+C by saving the current recording and exiting"""
    global recording, audio, frames
    print("\nCtrl+C detected. Saving last recording and exiting...")
    
    if recording and len(frames) > 0:
        save_recording(frames)
    
    if audio:
        audio.terminate()
    
    sys.exit(0)

def save_recording(frames):
    """Save the recorded frames to a WAV file with timestamp"""
    if not frames:
        return
    
    # Create recordings folder if it doesn't exist
    if not os.path.exists(RECORDINGS_FOLDER):
        os.makedirs(RECORDINGS_FOLDER)
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(RECORDINGS_FOLDER, f"recording_{timestamp}.wav")
    
    print(f"Saving recording to {filename}")
    
    # Save as WAV file
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(frames))
    
    print(f"Recording saved.")

def get_audio_level(data):
    """Calculate the audio level using absolute values"""
    data_np = np.frombuffer(data, dtype=np.int16)
    return np.mean(np.abs(data_np))

def main():
    global recording, audio, frames
    
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_exit)
    
    # Initialize PyAudio
    audio = pyaudio.PyAudio()
    
    # Get device info
    try:
        device_info = audio.get_device_info_by_index(MIC_INDEX)
        print(f"Using microphone: {device_info['name']}")
    except Exception as e:
        print(f"Error accessing microphone with index {MIC_INDEX}: {e}")
        audio.terminate()
        return
    
    # Open the input stream
    try:
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=MIC_INDEX,
            frames_per_buffer=CHUNK_SIZE
        )
    except Exception as e:
        print(f"Error opening audio stream: {e}")
        audio.terminate()
        return
    
    print(f"Ready to record. Listening for sound...")
    print("Press Ctrl+C to exit")
    
    # Main recording loop
    while True:
        # Wait for sound to begin
        print("Waiting for sound...")
        while True:
            try:
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                level = get_audio_level(data)
                if level > SILENCE_THRESHOLD:
                    print(f"Sound detected. Recording started.")
                    recording = True
                    frames = [data]  # Start with the first chunk that triggered recording
                    break
            except Exception as e:
                print(f"Error reading from stream: {e}")
                time.sleep(1)
        
        # Record until silence
        silence_counter = 0
        while recording:
            try:
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                frames.append(data)
                
                # Check for silence
                level = get_audio_level(data)
                
                if level <= SILENCE_THRESHOLD:
                    silence_counter += 1
                    if silence_counter >= FRAMES_PER_BUFFER:
                        print(f"Silence detected. Recording stopped.")
                        recording = False
                else:
                    silence_counter = 0
            except Exception as e:
                print(f"Error during recording: {e}")
        
        # Save the recording
        save_recording(frames)
        frames = []

if __name__ == "__main__":
    main()