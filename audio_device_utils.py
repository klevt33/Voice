# audio_device_utils.py
import logging
from typing import Dict, Any, Optional
import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)

def get_default_microphone_info(audio: pyaudio.PyAudio) -> Optional[Dict[str, Any]]:
    """
    Get default system microphone device info.
    
    Args:
        audio: PyAudio instance
        
    Returns:
        Device info dictionary or None if no default microphone available
    """
    try:
        default_input = audio.get_default_input_device_info()
        logger.info(f"Default microphone detected: {default_input['name']} (index {default_input['index']})")
        return default_input
    except Exception as e:
        logger.error(f"Failed to get default microphone: {e}")
        
        # Try to find first available input device as fallback
        try:
            device_count = audio.get_device_count()
            for i in range(device_count):
                device_info = audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    logger.info(f"Using fallback microphone: {device_info['name']} (index {i})")
                    return device_info
        except Exception as fallback_error:
            logger.error(f"Failed to find fallback microphone: {fallback_error}")
        
        return None

def get_default_speakers_loopback_info(audio: pyaudio.PyAudio) -> Optional[Dict[str, Any]]:
    """
    Get default system speakers loopback device info using pyaudiowpatch.
    
    Args:
        audio: PyAudio instance (must be pyaudiowpatch)
        
    Returns:
        Loopback device info dictionary or None if not found
    """
    try:
        # Get default output device
        default_speakers = audio.get_device_info_by_index(
            audio.get_default_output_device_info()['index']
        )
        
        logger.info(f"Default speakers detected: {default_speakers['name']} (index {default_speakers['index']})")
        
        # Find the corresponding loopback device
        if not default_speakers.get("isLoopbackDevice", False):
            logger.info("Searching for loopback device...")
            for loopback in audio.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    logger.info(f"Found loopback device: {loopback['name']} (index {loopback['index']})")
                    return loopback
            
            logger.warning(f"No loopback device found for speakers: {default_speakers['name']}")
            return None
        else:
            logger.info(f"Default speakers is already a loopback device: {default_speakers['name']}")
            return default_speakers
            
    except Exception as e:
        logger.error(f"Failed to get default speakers loopback: {e}")
        return None

def validate_device_info(device_info: Dict[str, Any], source: str) -> bool:
    """
    Validate device info for audio capture.
    
    Args:
        device_info: Device information dictionary
        source: Source type ("ME" or "OTHERS")
        
    Returns:
        True if device info is valid for capture, False otherwise
    """
    if not device_info:
        logger.error(f"No device info provided for {source}")
        return False
    
    required_keys = ['index', 'name', 'maxInputChannels', 'defaultSampleRate']
    for key in required_keys:
        if key not in device_info:
            logger.error(f"Missing required key '{key}' in device info for {source}")
            return False
    
    if device_info['maxInputChannels'] <= 0:
        logger.error(f"Device {device_info['name']} has no input channels for {source}")
        return False
    
    if device_info['defaultSampleRate'] <= 0:
        logger.error(f"Device {device_info['name']} has invalid sample rate for {source}")
        return False
    
    logger.info(f"Device validation successful for {source}: {device_info['name']}")
    return True

def format_device_info(device_info: Dict[str, Any]) -> str:
    """
    Format device info for logging and display.
    
    Args:
        device_info: Device information dictionary
        
    Returns:
        Formatted device info string
    """
    if not device_info:
        return "No device"
    
    name = device_info.get('name', 'Unknown')
    index = device_info.get('index', 'Unknown')
    channels = device_info.get('maxInputChannels', 0)
    sample_rate = device_info.get('defaultSampleRate', 0)
    
    return f"{name} (index {index}, {channels} channels, {sample_rate} Hz)"