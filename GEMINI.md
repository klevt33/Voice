# Gemini's Project Analysis

This file summarizes the project's architecture and functionality based on my analysis.

**Project:** Audio Transcription Processor

**Core Logic:** The main script is `AudioToChat.py`. It orchestrates the application, managing audio capture, transcription, and the UI.

**Audio Handling:**
- `audio_handler.py`: Captures audio from two devices.
- `config.py`: Defines the audio devices by their numeric indices.
- `scan_mics.py`: A standalone utility script to help users find the correct microphone indices.

**Transcription:**
- Uses the `faster-whisper` library for speech-to-text conversion.
- `transcription.py` manages the transcription process.

**User Interface:**
- `TopicsUI.py`: A `tkinter`-based GUI.
- Displays transcribed text from both audio sources.
- Allows the user to select, deselect, and delete transcriptions.

**Browser Automation:**
- `browser.py`: Uses `selenium` to automate a running Google Chrome instance.
- The Chrome instance must be launched with a remote debugging port (`--remote-debugging-port=9222`).
- Submits selected text to AI chat websites (e.g., Perplexity, ChatGPT).

**Standalone Utilities:**
- `tests/check_cuda.py`: A script to verify the CUDA and cuDNN setup for GPU acceleration.
- `tests/perplexity_selector_test.py`: A test script (as identified by the user).
- `tests/scan_mics.py`: A standalone utility script to help users find the correct microphone indices.
