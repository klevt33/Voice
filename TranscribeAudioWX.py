import os
os.add_dll_directory(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin")
os.add_dll_directory(r"C:\Program Files\NVIDIA\CUDNN\v8\bin")

import pyaudio
import wave
import numpy as np
import time
from datetime import datetime
import signal
import sys
import threading
import queue
import glob
import whisperx
import torch
import gc

# Enable TF32 for better performance
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

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
MODELS_FOLDER = "whisperx_models"  # Folder to save WhisperX models
WHISPER_MODEL = "medium"  # WhisperX model size (tiny, base, small, medium, large-v1, large-v2)
BATCH_SIZE = 8        # Batch size for transcription (reduce if low on GPU memory)
COMPUTE_TYPE = "float16"  # Compute type (float16, int8)
LANGUAGE = "en"       # Set to English only

# Global variables for signal handling
recording = False
audio = None
frames = []
run_threads = True
files_queue = queue.Queue()
processed_files = set()

def handle_exit(sig, frame):
    """Handle Ctrl+C by saving the current recording and exiting all threads"""
    global recording, audio, frames, run_threads
    print("\nCtrl+C detected. Saving last recording and shutting down...")
    
    if recording and len(frames) > 0:
        save_recording(frames)
    
    if audio:
        audio.terminate()
    
    run_threads = False
    
    # Allow some time for threads to clean up
    time.sleep(2)
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
    
    # Add file to processing queue
    files_queue.put(filename)

def get_audio_level(data):
    """Calculate the audio level using absolute values"""
    data_np = np.frombuffer(data, dtype=np.int16)
    return np.mean(np.abs(data_np))

def recording_thread():
    """Thread that handles audio recording"""
    global recording, audio, frames, run_threads
    
    # Initialize PyAudio
    audio = pyaudio.PyAudio()
    
    # Get device info
    try:
        device_info = audio.get_device_info_by_index(MIC_INDEX)
        print(f"Using microphone: {device_info['name']}")
    except Exception as e:
        print(f"Error accessing microphone with index {MIC_INDEX}: {e}")
        audio.terminate()
        run_threads = False
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
        run_threads = False
        return
    
    print(f"Ready to record. Listening for sound...")
    
    # Main recording loop
    while run_threads:
        # Wait for sound to begin
        print("Waiting for sound...")
        while run_threads:
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
            
            if not run_threads:
                break
        
        # Record until silence
        silence_counter = 0
        while recording and run_threads:
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
        
        # Save the recording if we have data
        if frames and len(frames) > 0:
            save_recording(frames)
            frames = []
    
    # Clean up
    stream.stop_stream()
    stream.close()
    audio.terminate()

def process_existing_files():
    """Find existing files in the recordings folder and add them to the queue"""
    if not os.path.exists(RECORDINGS_FOLDER):
        os.makedirs(RECORDINGS_FOLDER)
        return
    
    # Get all existing wav files sorted by creation time
    existing_files = glob.glob(os.path.join(RECORDINGS_FOLDER, "recording_*.wav"))
    existing_files.sort(key=os.path.getctime)
    
    print(f"Found {len(existing_files)} existing recordings.")
    
    # Add them to the processing queue
    for file in existing_files:
        files_queue.put(file)
        processed_files.add(file)

def transcription_thread():
    """Thread that processes audio files and converts speech to text using WhisperX"""
    global run_threads, processed_files
    
    print(f"Initializing WhisperX ({WHISPER_MODEL} model)...")
    
    # Handle CUDA availability
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    
    # Fall back to CPU if CUDA DLL issues occur
    try:
        if device == "cuda":
            # Test torch CUDA
            torch.zeros(1).cuda()
    except Exception as e:
        print(f"CUDA error detected: {e}")
        print("Falling back to CPU.")
        device = "cpu"
    
    # Create models folder if it doesn't exist
    if not os.path.exists(MODELS_FOLDER):
        os.makedirs(MODELS_FOLDER)
    
    # Initialize the model
    try:
        # Load the whisper model with local cache directory
        print("About to load WhisperX model...")
        model = whisperx.load_model(
            WHISPER_MODEL, 
            device, 
            compute_type=COMPUTE_TYPE if device == "cuda" else "int8",
            download_root=MODELS_FOLDER
        )
        print("WhisperX model loaded, type:", type(model))
        print("Speech recognition model loaded successfully.")
    except Exception as e:
        print(f"Error initializing WhisperX: {e}")
        print(f"Detailed error: {str(e)}")
        run_threads = False
        return
    
    print("Speech recognition thread ready.")
    
    # Process any existing files
    process_existing_files()
    
    # Main processing loop
    while run_threads:
        try:
            # Get the next file with a timeout to allow checking run_threads
            try:
                filename = files_queue.get(timeout=1)
            except queue.Empty:
                continue
            
            if filename in processed_files:
                files_queue.task_done()
                continue
                
            # Process the file
            print(f"\nTranscribing: {os.path.basename(filename)}")
            
            try:
                # Load audio file
                audio_data = whisperx.load_audio(filename)
                
                # Transcribe with whisperx - specifying English language
                result = model.transcribe(audio_data, batch_size=BATCH_SIZE, language=LANGUAGE)
                
                # No need to detect language - use English
                detected_language = LANGUAGE
                print(f"Using language: {detected_language}")
                
                # Attempt to load alignment model for English
                try:
                    align_model, metadata = whisperx.load_align_model(
                        language_code=detected_language, 
                        device=device,
                        model_dir=MODELS_FOLDER
                    )
                    
                    # Align the transcription
                    result = whisperx.align(
                        result["segments"], 
                        align_model, 
                        metadata, 
                        audio_data, 
                        device
                    )
                    
                    # Clean up alignment model to free memory
                    del align_model
                    gc.collect()
                    if device == "cuda":
                        torch.cuda.empty_cache()
                    
                except Exception as align_err:
                    print(f"Alignment skipped: {align_err}")
                
                # Print the transcript
                print("\n--- Transcript ---")
                for segment in result["segments"]:
                    print(f"[{segment.get('start', 0):.1f}s - {segment.get('end', 0):.1f}s] {segment.get('text', '')}")
                print("--- End Transcript ---\n")
                
                # Mark as processed
                processed_files.add(filename)
                files_queue.task_done()

                # Remove the audio file after processing
                try:
                    os.remove(filename)
                    print(f"Removed audio file: {os.path.basename(filename)}")
                except Exception as e:
                    print(f"Error removing file {filename}: {e}")
                    
            except Exception as e:
                print(f"Error transcribing {filename}: {e}")
                # Put it back in the queue to try again later
                files_queue.put(filename)
                time.sleep(1)
                
        except Exception as e:
            print(f"Error in transcription thread: {e}")
            time.sleep(1)
    
    # Clean up resources
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    
    print("Transcription thread shutting down.")

def main():
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_exit)
    
    # Create and start the recording thread
    recorder = threading.Thread(target=recording_thread)
    recorder.daemon = True
    recorder.start()
    
    # Create and start the transcription thread
    transcriber = threading.Thread(target=transcription_thread)
    transcriber.daemon = True
    transcriber.start()
    
    print("Press Ctrl+C to exit")
    
    # Keep the main thread alive until Ctrl+C
    try:
        while run_threads:
            time.sleep(0.1)
    except KeyboardInterrupt:
        handle_exit(None, None)

if __name__ == "__main__":
    main()