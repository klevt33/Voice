import os
os.add_dll_directory(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin")
os.add_dll_directory(r"C:\Program Files\NVIDIA\CUDNN\v8\bin")
from faster_whisper import WhisperModel
import torch

def test_faster_whisper():
    print("=== Faster Whisper Test Script ===")
    
    # Print CUDA information
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA device count: {torch.cuda.device_count()}")
        print(f"CUDA device name: {torch.cuda.get_device_name(0)}")
        print(f"CUDA version: {torch.version.cuda}")
    
    # Print PATH information
    print("\nPATH environment variable:")
    for path in os.environ["PATH"].split(";"):
        if "cuda" in path.lower() or "nvidia" in path.lower():
            print(f"  - {path}")
    
    # Check for audio file
    test_file = "recordings/recording_20250315_150302.wav"
    if not os.path.exists(test_file):
        print(f"\nTest audio file '{test_file}' not found.")
        print("Please provide an audio file named 'test_audio.wav' in the same directory.")
        return
    
    print(f"\nLoading model 'tiny' to test functionality...")
    try:
        # Use tiny model for quick testing
        model = WhisperModel(
            "tiny", 
            device="cuda" if torch.cuda.is_available() else "cpu",
            compute_type="float16" if torch.cuda.is_available() else "int8"
        )
        print("Model loaded successfully!")
        
        print(f"\nTranscribing test file: {test_file}")
        segments, info = model.transcribe(test_file, language="en")
        
        print(f"Detected language: {info.language} with probability {info.language_probability:.2f}")
        print("\n=== Transcription Results ===")
        
        for segment in segments:
            print(f"[{segment.start:.1f}s - {segment.end:.1f}s] {segment.text}")
        
        print("\nTest completed successfully!")
        
    except Exception as e:
        print(f"\nError during testing: {e}")
        print("\nDetailed error information:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_faster_whisper()