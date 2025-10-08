# Audio Transcription Processor - Setup Guide

This application supports flexible transcription options to work on different hardware configurations.

## Transcription Methods

The app supports two transcription methods:

### 1. Local Transcription (GPU/CPU)
- **Pros**: Fast, private, no internet required
- **Cons**: Requires PyTorch installation, uses disk space for models
- **Requirements**: PyTorch + faster-whisper

### 2. API Transcription (Groq)
- **Pros**: Works on any hardware, no local model downloads
- **Cons**: Requires internet connection and API key
- **Requirements**: Groq API key

## Installation Options

### Option A: API-Only Setup (Minimal)
Perfect for machines without GPU or when you prefer cloud transcription:

```bash
pip install -r requirements-api-only.txt
set GROQ_API_KEY=your_api_key_here
```

### Option B: Local-Only Setup
For offline use with GPU/CPU transcription:

```bash
# Install PyTorch first
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install other dependencies
pip install faster-whisper ctranslate2 sympy==1.13.1
pip install -r requirements-api-only.txt
```

### Option C: Full Setup (Both Methods)
For maximum flexibility with both local and API transcription:

```bash
# Install PyTorch first
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install all dependencies
pip install faster-whisper ctranslate2 sympy==1.13.1
pip install -r requirements-api-only.txt

# Set API key
set GROQ_API_KEY=your_api_key_here
```

## Configuration

Edit `config.py` to set your preferred transcription method:

```python
# Transcription method preference
DEFAULT_TRANSCRIPTION_METHOD = "auto"  # Options: "local", "api", "auto"
```

- **"local"**: Use local GPU/CPU transcription only
- **"api"**: Use Groq API transcription only  
- **"auto"**: Prefer local if available, otherwise use API

## Smart Behavior

The app automatically adapts based on available dependencies:

### When PyTorch is NOT installed:
- ✅ App starts successfully
- ✅ Uses API transcription automatically
- ✅ UI shows "API Only" (disabled checkbox)
- ✅ No local model downloads

### When PyTorch IS installed but DEFAULT_TRANSCRIPTION_METHOD = "api":
- ✅ App starts successfully
- ✅ Uses API transcription only
- ✅ No local model downloads (saves disk space)
- ✅ UI shows "Use API" (enabled checkbox)

### When both methods are available:
- ✅ User can switch between methods via UI
- ✅ Automatic fallback if one method fails
- ✅ Smart model loading based on configuration

## UI Controls

The transcription method checkbox appears in the Topics section:

- **Hidden**: When no transcription methods are available
- **"API Only" (disabled)**: When only API is available
- **"Local Only" (disabled)**: When only local transcription is available  
- **"Use API" (enabled)**: When both methods are available

## Troubleshooting

### "No transcription strategies available"
- Install PyTorch + faster-whisper OR set GROQ_API_KEY
- Check `python test_streamlined_config.py` for diagnostics

### "API Authentication Error"
- Verify GROQ_API_KEY environment variable is set correctly
- Check API key validity at https://console.groq.com/

### "CUDA Error" 
- App will automatically fall back to CPU or API
- Check GPU drivers and CUDA installation

### Local model downloads when using API-only
- Set `DEFAULT_TRANSCRIPTION_METHOD = "api"` in config.py
- This prevents unnecessary model downloads

## Environment Variables

- `GROQ_API_KEY`: Your Groq API key for cloud transcription

## Performance Tips

- **For GPU users**: Use "local" mode for fastest transcription
- **For CPU-only users**: Use "api" mode for better performance
- **For mixed usage**: Use "auto" mode with fallback enabled
- **To save disk space**: Use "api" mode to avoid model downloads