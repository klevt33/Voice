import os
os.add_dll_directory(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin")
os.add_dll_directory(r"C:\Program Files\NVIDIA\CUDNN\v8\bin")

import pyaudio
import numpy as np
import time
from datetime import datetime
import signal
import sys
import threading
import queue
import torch
from faster_whisper import WhisperModel
import gc
import io
import wave

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
MODELS_FOLDER = "faster_whisper_models"  # Folder to save faster_whisper models
WHISPER_MODEL = "medium"  # Whisper model size (tiny, base, small, medium, large-v1, large-v2)
COMPUTE_TYPE = "float16"  # Compute type (float16, int8)
LANGUAGE = "en"       # Set to English only
BEAM_SIZE = 5         # Beam size for faster-whisper

# Global variables for signal handling
recording = False
audio = None
frames = []
run_threads = True
audio_queue = queue.Queue()  # Queue for in-memory audio data
stream = None  # Added global stream variable to properly close it

class AudioSegment:
    """Class to store audio data in memory"""
    def __init__(self, frames, sample_rate, channels, sample_width):
        self.frames = frames
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def get_wav_bytes(self):
        """Convert frames to WAV file bytes in memory"""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b''.join(self.frames))
        wav_buffer.seek(0)
        return wav_buffer.read()
    
    def get_numpy_array(self):
        """Convert frames to numpy array for processing"""
        audio_data = np.frombuffer(b''.join(self.frames), dtype=np.int16)
        # Convert to float32 and normalize to range [-1, 1]
        return audio_data.astype(np.float32) / 32768.0

def handle_exit(sig, frame):
    """Handle Ctrl+C by processing the current recording and exiting all threads"""
    global recording, audio, frames, run_threads, stream
    print("\nCtrl+C detected. Processing last recording and shutting down...")
    
    # Stop the global flag first
    run_threads = False
    
    # Close stream properly if it exists and is active
    if stream is not None:
        try:
            if stream.is_active():
                stream.stop_stream()
            stream.close()
        except Exception as e:
            # Suppress the error message
            pass
    
    if recording and len(frames) > 0:
        process_recording(frames)
    
    if audio:
        audio.terminate()
    
    # Allow some time for threads to clean up
    time.sleep(2)
    sys.exit(0)

def process_recording(frames):
    """Process the recorded frames and add to in-memory queue"""
    if not frames:
        return
    
    print(f"Processing new audio segment")
    
    # Create audio segment object
    audio_segment = AudioSegment(
        frames=frames,
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        sample_width=audio.get_sample_size(FORMAT)
    )
    
    # Add to queue for processing
    audio_queue.put(audio_segment)
    print(f"Audio segment queued for transcription")

def get_audio_level(data):
    """Calculate the audio level using absolute values"""
    data_np = np.frombuffer(data, dtype=np.int16)
    return np.mean(np.abs(data_np))

def recording_thread():
    """Thread that handles audio recording"""
    global recording, audio, frames, run_threads, stream
    
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
                # Only print errors if we're still supposed to be running
                if run_threads:
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
                # Only print errors if we're still supposed to be running
                if run_threads:
                    print(f"Error during recording: {e}")
        
        # Process the recording if we have data
        if frames and len(frames) > 0:
            process_recording(frames)
            frames = []
    
    # Clean up - this might not be reached due to sys.exit in handle_exit
    # but we include it as a safeguard
    try:
        if stream.is_active():
            stream.stop_stream()
        stream.close()
    except Exception:
        pass
    
    audio.terminate()

def transcription_thread():
    """Thread that processes audio segments and converts speech to text using faster_whisper"""
    global run_threads
    
    print(f"Initializing faster_whisper ({WHISPER_MODEL} model)...")
    
    # Determine device type
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
        # Load the faster_whisper model
        print("About to load faster_whisper model...")
        model = WhisperModel(
            WHISPER_MODEL,
            device=device,
            compute_type=COMPUTE_TYPE if device == "cuda" else "int8",
            download_root=MODELS_FOLDER
        )
        print("faster_whisper model loaded successfully")
    except Exception as e:
        print(f"Error initializing faster_whisper: {e}")
        print(f"Detailed error: {str(e)}")
        run_threads = False
        return
    
    print("Speech recognition thread ready.")
    
    # Main processing loop
    while run_threads:
        try:
            # Get the next audio segment with a timeout to allow checking run_threads
            try:
                audio_segment = audio_queue.get(timeout=1)
            except queue.Empty:
                continue
                
            # Process the audio segment
            print(f"\nTranscribing audio recorded at {audio_segment.timestamp}")
            
            try:
                # Get audio data as WAV bytes
                audio_data = audio_segment.get_wav_bytes()
                
                # Transcribe with faster_whisper - specifying English language
                # Using BytesIO as the input source
                segments, info = model.transcribe(
                    io.BytesIO(audio_data),
                    language=LANGUAGE,
                    beam_size=BEAM_SIZE,
                    word_timestamps=False  # Don't need word timestamps
                )
                
                # Print transcription information
                print(f"Detected language: {info.language} with probability {info.language_probability:.2f}")
                
                # Print the transcript without timestamps
                print("\n--- Transcript ---")
                transcript_text = ""
                segment_list = list(segments)  # Convert generator to list
                
                if not segment_list:
                    print("No speech detected.")
                else:
                    # Combine all segments into one continuous text
                    for segment in segment_list:
                        transcript_text += segment.text + " "
                    
                    # Print the full transcript without timestamps
                    print(transcript_text.strip())
                        
                print("--- End Transcript ---\n")
                
                audio_queue.task_done()
                    
            except Exception as e:
                print(f"Error transcribing audio: {e}")
                # Put it back in the queue to try again later
                audio_queue.put(audio_segment)
                time.sleep(1)
                
        except Exception as e:
            print(f"Error in transcription thread: {e}")
            time.sleep(1)
            
        # Check if we should exit
        if not run_threads:
            break
    
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