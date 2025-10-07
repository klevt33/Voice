# transcription.py
import io
import time
import torch
import gc
import queue
import logging
from typing import Dict, Optional, Any
from faster_whisper import WhisperModel
import os
import re
from datetime import datetime
from TopicsUI import Topic
from config import (WHISPER_MODEL, COMPUTE_TYPE, MODELS_FOLDER, LANGUAGE, BEAM_SIZE,
                   DEFAULT_TRANSCRIPTION_METHOD, validate_transcription_config)
from transcription_strategies import (TranscriptionManager, LocalGPUTranscriptionStrategy, 
                                    GroqAPITranscriptionStrategy, StrategyConfig)

# Configure logger for this module
logger = logging.getLogger(__name__)

# Cache for models to avoid reloading
_model_cache = {}

# Global transcription manager instance
_transcription_manager: Optional[TranscriptionManager] = None

def get_whisper_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    """Get a cached whisper model or create a new one"""
    cache_key = f"{model_name}_{device}_{compute_type}"
    if cache_key not in _model_cache:
        logger.info(f"Creating new WhisperModel instance: {model_name} on {device}")
        _model_cache[cache_key] = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=MODELS_FOLDER
        )
    else:
        logger.info(f"Using cached WhisperModel instance: {model_name}")
    return _model_cache[cache_key]

def initialize_transcription_manager() -> TranscriptionManager:
    """Initialize and configure the transcription manager"""
    global _transcription_manager
    
    if _transcription_manager is not None:
        return _transcription_manager
    
    logger.info("Initializing transcription manager...")
    
    # Validate configuration
    config_validation = validate_transcription_config()
    if not config_validation["config_valid"]:
        for error in config_validation["errors"]:
            logger.error(f"Configuration error: {error}")
        raise RuntimeError("Invalid transcription configuration")
    
    for warning in config_validation["warnings"]:
        logger.warning(f"Configuration warning: {warning}")
    
    # Create transcription manager
    manager = TranscriptionManager()
    
    # Initialize local GPU strategy
    try:
        local_config = StrategyConfig(
            name="local_gpu",
            enabled=True,
            priority=1,
            timeout=30.0,
            retry_count=1,
            specific_config={}
        )
        local_strategy = LocalGPUTranscriptionStrategy(local_config)
        manager.register_strategy(local_strategy)
        logger.info("Local GPU transcription strategy registered")
    except Exception as e:
        logger.warning(f"Failed to initialize local GPU strategy: {e}")
    
    # Initialize Groq API strategy if available
    if config_validation["groq_api_available"]:
        try:
            api_config = StrategyConfig(
                name="groq_api",
                enabled=True,
                priority=2,
                timeout=30.0,
                retry_count=3,
                specific_config={}
            )
            api_strategy = GroqAPITranscriptionStrategy(api_config)
            manager.register_strategy(api_strategy)
            logger.info("Groq API transcription strategy registered")
        except Exception as e:
            logger.warning(f"Failed to initialize Groq API strategy: {e}")
    
    # Set up primary and fallback strategies based on configuration and availability
    available_strategies = manager.get_available_strategies()
    logger.info(f"Available transcription strategies: {available_strategies}")
    
    # Determine primary strategy based on configuration
    primary_set = False
    fallback_set = False
    
    if DEFAULT_TRANSCRIPTION_METHOD == "local" and available_strategies.get("Local GPU (CUDA)", False):
        manager.set_primary_strategy("Local GPU (CUDA)")
        primary_set = True
        if available_strategies.get("Groq API", False):
            manager.set_fallback_strategy("Groq API")
            fallback_set = True
    elif DEFAULT_TRANSCRIPTION_METHOD == "local" and available_strategies.get("Local GPU (CPU)", False):
        manager.set_primary_strategy("Local GPU (CPU)")
        primary_set = True
        if available_strategies.get("Groq API", False):
            manager.set_fallback_strategy("Groq API")
            fallback_set = True
    elif DEFAULT_TRANSCRIPTION_METHOD == "api" and available_strategies.get("Groq API", False):
        manager.set_primary_strategy("Groq API")
        primary_set = True
        if available_strategies.get("Local GPU (CUDA)", False):
            manager.set_fallback_strategy("Local GPU (CUDA)")
            fallback_set = True
        elif available_strategies.get("Local GPU (CPU)", False):
            manager.set_fallback_strategy("Local GPU (CPU)")
            fallback_set = True
    else:  # auto mode or fallback
        # Prefer local GPU if available, otherwise API
        if available_strategies.get("Local GPU (CUDA)", False):
            manager.set_primary_strategy("Local GPU (CUDA)")
            primary_set = True
            if available_strategies.get("Groq API", False):
                manager.set_fallback_strategy("Groq API")
                fallback_set = True
        elif available_strategies.get("Local GPU (CPU)", False):
            manager.set_primary_strategy("Local GPU (CPU)")
            primary_set = True
            if available_strategies.get("Groq API", False):
                manager.set_fallback_strategy("Groq API")
                fallback_set = True
        elif available_strategies.get("Groq API", False):
            manager.set_primary_strategy("Groq API")
            primary_set = True
    
    if not primary_set:
        raise RuntimeError("No transcription strategies available")
    
    logger.info(f"Primary strategy: {manager.get_current_strategy_name()}")
    if fallback_set:
        logger.info("Fallback strategy configured")
    
    _transcription_manager = manager
    return manager

def get_transcription_manager() -> Optional[TranscriptionManager]:
    """Get the global transcription manager instance"""
    return _transcription_manager

def switch_transcription_method(method_name: str) -> bool:
    """
    Switch transcription method during runtime
    
    Args:
        method_name: Name of the method to switch to ("local_gpu", "groq_api", etc.)
        
    Returns:
        True if successful, False otherwise
    """
    global _transcription_manager
    
    if _transcription_manager is None:
        logger.error("Transcription manager not initialized")
        return False
    
    # Map user-friendly names to strategy names
    strategy_mapping = {
        "local": "Local GPU (CUDA)",
        "local_gpu": "Local GPU (CUDA)", 
        "local_cpu": "Local GPU (CPU)",
        "api": "Groq API",
        "groq": "Groq API",
        "groq_api": "Groq API"
    }
    
    # Try direct name first, then mapping
    strategy_name = strategy_mapping.get(method_name.lower(), method_name)
    
    # Check available strategies
    available = _transcription_manager.get_available_strategies()
    if strategy_name not in available:
        # Try alternative names
        for alt_name in available.keys():
            if method_name.lower() in alt_name.lower():
                strategy_name = alt_name
                break
        else:
            logger.error(f"Strategy not found: {method_name}. Available: {list(available.keys())}")
            return False
    
    if not available[strategy_name]:
        logger.error(f"Strategy not available: {strategy_name}")
        return False
    
    success = _transcription_manager.switch_strategy(strategy_name)
    if success:
        logger.info(f"Successfully switched transcription method to: {strategy_name}")
    else:
        logger.error(f"Failed to switch transcription method to: {strategy_name}")
    
    return success

def get_current_transcription_method() -> Optional[str]:
    """Get the current transcription method name"""
    global _transcription_manager
    
    if _transcription_manager is None:
        return None
    
    return _transcription_manager.get_current_strategy_name()

def get_available_transcription_methods() -> Dict[str, bool]:
    """Get available transcription methods and their availability status"""
    global _transcription_manager
    
    if _transcription_manager is None:
        return {}
    
    return _transcription_manager.get_available_strategies()

def get_transcription_health_status() -> Dict[str, Dict]:
    """Get health status of all transcription strategies"""
    global _transcription_manager
    
    if _transcription_manager is None:
        return {}
    
    return _transcription_manager.get_strategy_health()

def is_gpu_available() -> bool:
    """Check if GPU is available for local transcription"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

def is_api_available() -> bool:
    """Check if API transcription is available"""
    from config import is_groq_api_available
    return is_groq_api_available()

def get_transcription_capabilities() -> Dict[str, bool]:
    """Get transcription capabilities for UI control"""
    return {
        "gpu_available": is_gpu_available(),
        "api_available": is_api_available(),
        "both_available": is_gpu_available() and is_api_available(),
        "fallback_enabled": True  # Always enabled in our implementation
    }

def get_transcription_performance_stats() -> Dict[str, Any]:
    """Get transcription performance statistics"""
    global _transcription_manager
    
    if _transcription_manager is None:
        return {}
    
    return _transcription_manager.get_performance_stats()

def get_transcription_performance_summary() -> str:
    """Get human-readable transcription performance summary"""
    global _transcription_manager
    
    if _transcription_manager is None:
        return "Transcription manager not initialized"
    
    return _transcription_manager.get_performance_summary()

def log_performance_summary():
    """Log current performance summary"""
    try:
        summary = get_transcription_performance_summary()
        logger.info(f"Transcription Performance:\n{summary}")
    except Exception as e:
        logger.error(f"Error logging performance summary: {e}")

def optimize_transcription_memory():
    """Optimize transcription system memory usage"""
    global _transcription_manager
    
    try:
        if _transcription_manager:
            _transcription_manager.optimize_memory_usage()
        
        # Clean up global model cache if it gets too large
        global _model_cache
        if len(_model_cache) > 3:  # Keep only 3 most recent models
            logger.info("Cleaning up model cache to free memory")
            _model_cache.clear()
            
            # Force garbage collection
            import gc
            gc.collect()
            
            # Clear CUDA cache if available
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.debug("CUDA cache cleared")
            except ImportError:
                pass
                
        logger.debug("Transcription memory optimization completed")
        
    except Exception as e:
        logger.error(f"Error optimizing transcription memory: {e}")

def cleanup_transcription_system():
    """Cleanup the entire transcription system"""
    global _transcription_manager, _model_cache
    
    try:
        if _transcription_manager:
            _transcription_manager.cleanup()
            _transcription_manager = None
        
        # Clear global model cache
        _model_cache.clear()
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Clear CUDA cache if available
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
            
        logger.info("Transcription system cleanup completed")
        
    except Exception as e:
        logger.error(f"Error cleaning up transcription system: {e}")

def transcription_thread(audio_queue: queue.Queue,
                         transcribed_topics_queue: queue.Queue,
                         run_threads_ref: Dict[str, bool],
                         exception_notifier=None) -> None:
    """
    Thread that processes audio segments, converts speech to text using TranscriptionManager,
    and puts the resulting Topic object into a queue.
    """
    logger.info("Initializing transcription manager...")
    
    # Initialize transcription manager
    try:
        manager = initialize_transcription_manager()
        logger.info("Transcription manager initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing transcription manager: {e}")
        
        # Notify about initialization error
        if exception_notifier:
            exception_notifier.notify_exception("transcription", e, "error", 
                                              "Transcription initialization failed")
        
        # Don't set run_threads_ref["active"] = False here as it affects other threads
        # Just return from this thread
        logger.error("Transcription thread exiting due to initialization failure")
        return
    
    logger.info("Speech recognition thread ready.")
    
    # Stats for monitoring performance
    stats = {
        "segments_processed": 0,
        "empty_segments": 0,
        "errors": 0,
        "fallback_used": 0,
        "total_processing_time": 0,
        "method_stats": {}
    }
    
    # Performance optimization tracking
    last_optimization_time = time.time()
    optimization_interval = 300  # 5 minutes
    
    # Main processing loop
    while run_threads_ref["active"]:
        try:
            # Check if manager is still available
            if manager is None:
                logger.error("Transcription manager is None, exiting thread")
                break
                
            # Get the next audio segment with a timeout to allow checking run_threads
            try:
                audio_segment = audio_queue.get(timeout=1)
            except queue.Empty:
                continue
                
            # Process the audio segment
            source_prefix = f"[{audio_segment.source}]"
            
            try:
                # Transcribe using the manager (with automatic fallback)
                result = manager.transcribe_with_fallback(audio_segment)
                
                # Update statistics
                stats["segments_processed"] += 1
                stats["total_processing_time"] += result.processing_time
                
                # Track method usage
                method = result.method_used
                if method not in stats["method_stats"]:
                    stats["method_stats"][method] = {"count": 0, "total_time": 0.0}
                stats["method_stats"][method]["count"] += 1
                stats["method_stats"][method]["total_time"] += result.processing_time
                
                if result.fallback_used:
                    stats["fallback_used"] += 1
                
                # Handle transcription result
                if result.error_message:
                    logger.warning(f"{source_prefix} Transcription failed: {result.error_message}")
                    stats["errors"] += 1
                    
                    # Notify about transcription errors
                    if exception_notifier:
                        _handle_transcription_error(exception_notifier, result.error_message, result.method_used)
                    
                    # Put it back in the queue to try again later
                    audio_queue.put(audio_segment)
                    time.sleep(1)
                    continue
                
                if not result.text:
                    logger.debug(f"{source_prefix} No speech detected.")
                    stats["empty_segments"] += 1
                else:
                    # Create a Topic object and queue it for the main app to route
                    topic = Topic(text=result.text, timestamp=datetime.now(), source=audio_segment.source)
                    transcribed_topics_queue.put(topic)
                    
                    fallback_info = " (fallback)" if result.fallback_used else ""
                    logger.info(f"TRANSCRIBED ({result.method_used}{fallback_info}): [{topic.source}] {result.text[:50]}...")
                    
                    # Clear any active transcription exceptions on successful transcription
                    if exception_notifier:
                        exception_notifier.clear_exception_status("transcription")

                audio_queue.task_done()
                logger.debug(f"Processed segment in {result.processing_time:.2f}s using {result.method_used}")
                    
            except Exception as e:
                logger.error(f"Error transcribing {source_prefix} audio: {e}")
                
                # Notify about general transcription errors
                if exception_notifier:
                    exception_notifier.notify_exception("transcription", e, "error", 
                                                      "Transcription Error - Processing failed")
                
                # Put it back in the queue to try again later
                audio_queue.put(audio_segment)
                stats["errors"] += 1
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in transcription thread: {e}")
            
            # Notify about general transcription thread errors
            if exception_notifier:
                exception_notifier.notify_exception("transcription", e, "error", 
                                                  "Transcription thread error")
            
            stats["errors"] += 1
            time.sleep(1)
            
        # Periodic memory optimization
        current_time = time.time()
        if current_time - last_optimization_time > optimization_interval:
            try:
                optimize_transcription_memory()
                last_optimization_time = current_time
                logger.debug("Performed periodic memory optimization")
            except Exception as e:
                logger.warning(f"Error during periodic optimization: {e}")
        
        # Check if we should exit
        if not run_threads_ref["active"]:
            break
    
    # Print stats before exiting
    if stats["segments_processed"] > 0:
        avg_time = stats["total_processing_time"] / stats["segments_processed"] if stats["segments_processed"] > 0 else 0
        logger.info(f"Transcription stats: processed {stats['segments_processed']} segments, "
                   f"{stats['empty_segments']} empty, {stats['errors']} errors, "
                   f"{stats['fallback_used']} fallbacks, avg time: {avg_time:.2f}s per segment")
        
        # Log method-specific stats
        for method, method_stats in stats["method_stats"].items():
            method_avg = method_stats["total_time"] / method_stats["count"] if method_stats["count"] > 0 else 0
            logger.info(f"  {method}: {method_stats['count']} segments, avg time: {method_avg:.2f}s")
    
    # Clean up resources
    logger.info("Cleaning up transcription resources")
    try:
        manager.cleanup()
    except Exception as e:
        logger.warning(f"Error during transcription manager cleanup: {e}")
    
    logger.info("Transcription thread shutting down.")

def _handle_transcription_error(exception_notifier, error_message: str, method_used: str):
    """Handle transcription errors and notify appropriately"""
    error_lower = error_message.lower()
    
    # Create exception object with method context
    error_exception = Exception(f"[{method_used}] {error_message}")
    
    if "cuda" in error_lower or "gpu" in error_lower:
        if "out of memory" in error_lower:
            exception_notifier.notify_exception("transcription", error_exception, "error", 
                                              "CUDA Error - GPU out of memory")
        elif "driver" in error_lower:
            exception_notifier.notify_exception("transcription", error_exception, "error", 
                                              "CUDA Error - GPU driver issue")
        else:
            exception_notifier.notify_exception("transcription", error_exception, "error", 
                                              "CUDA Error - Transcription unavailable")
    elif "authentication_error" in error_lower or "api key" in error_lower:
        exception_notifier.notify_exception("transcription", error_exception, "error", 
                                          "API Authentication Error - Check API key")
    elif "rate_limit_error" in error_lower or "quota" in error_lower:
        exception_notifier.notify_exception("transcription", error_exception, "warning", 
                                          "API Rate Limit Exceeded - Using fallback")
    elif "network_error" in error_lower or "connection" in error_lower:
        exception_notifier.notify_exception("transcription", error_exception, "warning", 
                                          "API Network Error - Check connection")
    elif "api_error" in error_lower or ("groq" in error_lower and "api" in error_lower):
        exception_notifier.notify_exception("transcription", error_exception, "error", 
                                          "API Service Error - Transcription failed")
    else:
        exception_notifier.notify_exception("transcription", error_exception, "error", 
                                          f"Transcription Error ({method_used})")
