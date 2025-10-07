# transcription_strategies.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional
import logging
import os
import time
import io
from datetime import datetime
from audio_handler import AudioSegment

# Configure logger for this module
logger = logging.getLogger(__name__)

@dataclass
class TranscriptionResult:
    """Result of a transcription operation"""
    text: str
    method_used: str  # "local_gpu", "groq_api"
    processing_time: float
    fallback_used: bool
    error_message: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class StrategyConfig:
    """Configuration for a transcription strategy"""
    name: str
    enabled: bool
    priority: int
    timeout: float
    retry_count: int
    specific_config: Dict[str, Any]

class TranscriptionStrategy(ABC):
    """Abstract base class for transcription strategies"""
    
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._last_error = None
        self._error_count = 0
        self._last_success_time = None
    
    @abstractmethod
    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """
        Transcribe audio segment and return result
        
        Args:
            audio_segment: AudioSegment object containing audio data
            
        Returns:
            TranscriptionResult with transcription text and metadata
            
        Raises:
            TranscriptionError: If transcription fails
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if transcription method is available
        
        Returns:
            True if the strategy can be used, False otherwise
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """
        Get strategy name for logging/UI
        
        Returns:
            Human-readable name of the strategy
        """
        pass
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status of the strategy
        
        Returns:
            Dictionary with health information
        """
        return {
            "name": self.get_name(),
            "available": self.is_available(),
            "enabled": self.config.enabled,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "last_success_time": self._last_success_time
        }
    
    def _record_success(self):
        """Record a successful transcription"""
        self._last_success_time = datetime.now()
        self._error_count = 0
        self._last_error = None
    
    def _record_error(self, error: Exception):
        """Record a transcription error"""
        self._error_count += 1
        self._last_error = str(error)
        self.logger.error(f"Transcription error in {self.get_name()}: {error}")
    
    def cleanup(self):
        """
        Cleanup resources used by the strategy
        Override in subclasses if needed
        """
        pass

class TranscriptionError(Exception):
    """Exception raised when transcription fails"""
    
    def __init__(self, message: str, strategy_name: str, original_error: Exception = None):
        self.message = message
        self.strategy_name = strategy_name
        self.original_error = original_error
        super().__init__(f"[{strategy_name}] {message}")


class LocalGPUTranscriptionStrategy(TranscriptionStrategy):
    """Local GPU transcription strategy using faster-whisper"""
    
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self._model = None
        self._device = None
        self._model_cache = {}
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the faster-whisper model"""
        try:
            import torch
            from faster_whisper import WhisperModel
            from config import WHISPER_MODEL, COMPUTE_TYPE, MODELS_FOLDER
            
            # Determine device type - let faster-whisper handle the details
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self.logger.info(f"Initializing faster-whisper on device: {self._device}")
            
            # Create models folder if it doesn't exist
            if not os.path.exists(MODELS_FOLDER):
                os.makedirs(MODELS_FOLDER)
                self.logger.info(f"Created models folder: {MODELS_FOLDER}")
            
            # Create the model - let faster-whisper handle GPU/CPU logic
            compute_type = COMPUTE_TYPE if self._device == "cuda" else "int8"
            self._model = WhisperModel(
                WHISPER_MODEL,
                device=self._device,
                compute_type=compute_type,
                download_root=MODELS_FOLDER
            )
            
            self.logger.info(f"faster-whisper model loaded successfully on {self._device}")
            
        except Exception as e:
            self.logger.error(f"Error initializing faster-whisper: {e}")
            self._record_error(e)
            raise TranscriptionError(f"Failed to initialize local GPU transcription: {e}", self.get_name(), e)
    
    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """Transcribe audio using local faster-whisper model"""
        if not self.is_available():
            raise TranscriptionError("Local GPU transcription not available", self.get_name())
        
        start_time = time.time()
        
        try:
            from config import LANGUAGE, BEAM_SIZE
            import re
            
            # Get audio data as WAV bytes
            audio_data = audio_segment.get_wav_bytes()
            if not audio_data:
                raise TranscriptionError("Could not get WAV data from audio segment", self.get_name())
            
            # Transcribe with faster_whisper
            with io.BytesIO(audio_data) as audio_io:
                segments, info = self._model.transcribe(
                    audio_io,
                    language=LANGUAGE,
                    beam_size=BEAM_SIZE,
                    word_timestamps=False
                )
                
                # Process the transcript
                segment_list = list(segments)  # Convert generator to list
                
                if not segment_list:
                    # No speech detected
                    result_text = ""
                else:
                    # Combine all segments into one continuous text
                    transcript_text = " ".join(segment.text for segment in segment_list)
                    cleaned_text = transcript_text.strip()
                    
                    # Replace multiple consecutive spaces with a single space
                    cleaned_text = re.sub(r' {2,}', ' ', cleaned_text)
                    
                    # Filter out likely hallucinations or junk
                    if ("thank" in cleaned_text.lower() and len(cleaned_text) <= 40) or len(cleaned_text) <= 10:
                        self.logger.info(f"Filtered out likely hallucination: {cleaned_text}")
                        result_text = ""
                    else:
                        result_text = cleaned_text
            
            processing_time = time.time() - start_time
            self._record_success()
            
            return TranscriptionResult(
                text=result_text,
                method_used="local_gpu",
                processing_time=processing_time,
                fallback_used=False
            )
            
        except Exception as e:
            self._record_error(e)
            processing_time = time.time() - start_time
            
            return TranscriptionResult(
                text="",
                method_used="local_gpu",
                processing_time=processing_time,
                fallback_used=False,
                error_message=str(e)
            )
    
    def is_available(self) -> bool:
        """Check if local transcription is available"""
        return self._model is not None
    
    def get_name(self) -> str:
        """Get strategy name"""
        return f"Local GPU ({self._device.upper()})" if self._device else "Local GPU"
    
    def cleanup(self):
        """Cleanup GPU resources"""
        try:
            if self._model:
                del self._model
                self._model = None
            
            if self._device == "cuda":
                try:
                    import torch
                    import gc
                    gc.collect()
                    torch.cuda.empty_cache()
                    self.logger.debug("CUDA cache cleared")
                except ImportError:
                    pass
                
            self.logger.info("Local GPU transcription resources cleaned up")
        except Exception as e:
            self.logger.warning(f"Error during cleanup: {e}")


class GroqAPITranscriptionStrategy(TranscriptionStrategy):
    """Groq API transcription strategy using cloud-based Whisper"""
    
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self._client = None
        self._api_key = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Groq API client"""
        try:
            from config import get_groq_api_key, GROQ_MODEL
            
            self._api_key = get_groq_api_key()
            if not self._api_key:
                self.logger.warning("Groq API key not found in environment variables")
                return
            
            # Import Groq client
            try:
                from groq import Groq
                self._client = Groq(api_key=self._api_key)
                self.logger.info("Groq API client initialized successfully")
            except ImportError as e:
                self.logger.error("Groq package not installed. Install with: pip install groq")
                raise TranscriptionError("Groq package not available", self.get_name(), e)
                
        except Exception as e:
            self.logger.error(f"Error initializing Groq API client: {e}")
            self._record_error(e)
    
    def transcribe(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """Transcribe audio using Groq API with retry logic"""
        if not self.is_available():
            raise TranscriptionError("Groq API transcription not available", self.get_name())
        
        start_time = time.time()
        
        # Validate audio for API compatibility
        is_valid, validation_error = audio_segment.is_valid_for_api()
        if not is_valid:
            return TranscriptionResult(
                text="",
                method_used="groq_api",
                processing_time=time.time() - start_time,
                fallback_used=False,
                error_message=f"Audio validation failed: {validation_error}"
            )
        
        # Attempt transcription with retry logic
        return self._transcribe_with_retry(audio_segment, start_time)
    
    def _transcribe_with_retry(self, audio_segment: AudioSegment, start_time: float) -> TranscriptionResult:
        """Perform transcription with exponential backoff retry"""
        from config import API_RETRY_COUNT, API_RETRY_BACKOFF, GROQ_MODEL
        import time as time_module
        
        last_error = None
        
        for attempt in range(API_RETRY_COUNT + 1):  # +1 for initial attempt
            try:
                # Get API-compatible audio data
                audio_data = audio_segment.get_api_compatible_wav_bytes()
                if not audio_data:
                    raise TranscriptionError("Could not get API-compatible WAV data", self.get_name())
                
                audio_size_mb = len(audio_data) / (1024 * 1024)
                self.logger.debug(f"Attempt {attempt + 1}: Sending {audio_size_mb:.2f}MB audio to Groq API...")
                
                # Create transcription request with timeout handling
                transcription = self._make_api_request(audio_data, GROQ_MODEL)
                
                # Extract and process text
                result_text = self._process_transcription_response(transcription)
                
                processing_time = time_module.time() - start_time
                self._record_success()
                
                self.logger.info(f"Groq API transcription completed in {processing_time:.2f}s (attempt {attempt + 1})")
                
                return TranscriptionResult(
                    text=result_text,
                    method_used="groq_api",
                    processing_time=processing_time,
                    fallback_used=False
                )
                
            except Exception as e:
                last_error = e
                error_type = self._categorize_error(e)
                
                # Don't retry for certain error types
                if error_type in ["authentication_error", "validation_error"]:
                    self.logger.error(f"Non-retryable error: {error_type} - {e}")
                    break
                
                # Log retry attempt
                if attempt < API_RETRY_COUNT:
                    backoff_time = API_RETRY_BACKOFF ** attempt
                    self.logger.warning(f"API request failed (attempt {attempt + 1}), retrying in {backoff_time:.1f}s: {e}")
                    time_module.sleep(backoff_time)
                else:
                    self.logger.error(f"API request failed after {API_RETRY_COUNT + 1} attempts: {e}")
        
        # All attempts failed
        self._record_error(last_error)
        processing_time = time_module.time() - start_time
        error_type = self._categorize_error(last_error)
        
        return TranscriptionResult(
            text="",
            method_used="groq_api",
            processing_time=processing_time,
            fallback_used=False,
            error_message=f"{error_type}: {last_error}"
        )
    
    def _make_api_request(self, audio_data: bytes, model: str):
        """Make API request with timeout handling"""
        from config import API_REQUEST_TIMEOUT
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError(f"API request timed out after {API_REQUEST_TIMEOUT}s")
        
        # Set up timeout (Unix-like systems)
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(API_REQUEST_TIMEOUT))
            
            try:
                transcription = self._client.audio.transcriptions.create(
                    file=("audio.wav", audio_data),
                    model=model,
                    response_format="verbose_json",
                    language="en"
                )
                return transcription
            finally:
                signal.alarm(0)  # Cancel the alarm
                signal.signal(signal.SIGALRM, old_handler)
                
        except (AttributeError, OSError):
            # Windows or signal not available, use basic request without timeout signal
            # The Groq client should have its own timeout handling
            transcription = self._client.audio.transcriptions.create(
                file=("audio.wav", audio_data),
                model=model,
                response_format="verbose_json",
                language="en"
            )
            return transcription
    
    def _process_transcription_response(self, transcription) -> str:
        """Process and filter transcription response"""
        result_text = transcription.text.strip() if transcription.text else ""
        
        # Apply same filtering as local transcription
        if result_text:
            import re
            # Replace multiple consecutive spaces with a single space
            result_text = re.sub(r' {2,}', ' ', result_text)
            
            # Filter out likely hallucinations or junk
            if ("thank" in result_text.lower() and len(result_text) <= 40) or len(result_text) <= 10:
                self.logger.info(f"Filtered out likely hallucination: {result_text}")
                result_text = ""
        
        return result_text
    
    def _categorize_error(self, error: Exception) -> str:
        """Categorize API errors for appropriate handling"""
        error_message = str(error).lower()
        
        if "authentication" in error_message or "api key" in error_message or "unauthorized" in error_message:
            return "authentication_error"
        elif "rate limit" in error_message or "quota" in error_message or "too many requests" in error_message:
            return "rate_limit_error"
        elif "timeout" in error_message or "connection" in error_message or "network" in error_message:
            return "network_error"
        elif "validation" in error_message or "invalid" in error_message:
            return "validation_error"
        else:
            return "api_error"
    
    def is_available(self) -> bool:
        """Check if Groq API transcription is available"""
        try:
            from config import is_groq_api_available
            return self._client is not None and is_groq_api_available()
        except ImportError:
            return False
    
    def get_name(self) -> str:
        """Get strategy name"""
        return "Groq API"
    
    def _validate_api_key(self) -> bool:
        """Validate API key by making a test request (optional)"""
        # This could be implemented to test the API key validity
        # For now, we just check if the key exists
        return self._api_key is not None and len(self._api_key.strip()) > 0
    
    def cleanup(self):
        """Cleanup API resources"""
        try:
            if self._client:
                # Close any open connections (if the client supports it)
                self._client = None
            
            self._api_key = None
            self.logger.info("Groq API transcription resources cleaned up")
        except Exception as e:
            self.logger.warning(f"Error during API cleanup: {e}")


class TranscriptionManager:
    """Manages transcription strategies and handles fallback logic"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.TranscriptionManager")
        self._strategies = {}
        self._primary_strategy = None
        self._fallback_strategy = None
        self._current_strategy_name = None
        self._fallback_counts = {}
        self._last_fallback_time = {}
        self._strategy_lock = None
        self._performance_stats = {}
        self._initialize_lock()
        self._initialize_performance_tracking()
    
    def _initialize_lock(self):
        """Initialize thread lock for strategy switching"""
        try:
            import threading
            self._strategy_lock = threading.RLock()
        except ImportError:
            self.logger.warning("Threading not available, strategy switching may not be thread-safe")
    
    def _initialize_performance_tracking(self):
        """Initialize performance tracking data structures"""
        self._performance_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "fallback_requests": 0,
            "total_processing_time": 0.0,
            "strategy_stats": {},
            "recent_performance": []  # Last 100 requests for moving averages
        }
    
    def register_strategy(self, strategy: TranscriptionStrategy):
        """Register a transcription strategy"""
        strategy_name = strategy.get_name()
        self._strategies[strategy_name] = strategy
        self._fallback_counts[strategy_name] = 0
        self._last_fallback_time[strategy_name] = None
        self.logger.info(f"Registered transcription strategy: {strategy_name}")
    
    def set_primary_strategy(self, strategy_name: str) -> bool:
        """
        Set the primary transcription strategy
        
        Args:
            strategy_name: Name of the strategy to set as primary
            
        Returns:
            True if successful, False otherwise
        """
        if self._strategy_lock:
            with self._strategy_lock:
                return self._set_primary_strategy_unsafe(strategy_name)
        else:
            return self._set_primary_strategy_unsafe(strategy_name)
    
    def _set_primary_strategy_unsafe(self, strategy_name: str) -> bool:
        """Set primary strategy without locking (internal use)"""
        if strategy_name not in self._strategies:
            self.logger.error(f"Strategy not found: {strategy_name}")
            return False
        
        strategy = self._strategies[strategy_name]
        if not strategy.is_available():
            self.logger.warning(f"Strategy not available: {strategy_name}")
            return False
        
        self._primary_strategy = strategy
        self._current_strategy_name = strategy_name
        self.logger.info(f"Primary transcription strategy set to: {strategy_name}")
        return True
    
    def set_fallback_strategy(self, strategy_name: str) -> bool:
        """
        Set the fallback transcription strategy
        
        Args:
            strategy_name: Name of the strategy to set as fallback
            
        Returns:
            True if successful, False otherwise
        """
        if strategy_name not in self._strategies:
            self.logger.error(f"Fallback strategy not found: {strategy_name}")
            return False
        
        strategy = self._strategies[strategy_name]
        if not strategy.is_available():
            self.logger.warning(f"Fallback strategy not available: {strategy_name}")
            return False
        
        self._fallback_strategy = strategy
        self.logger.info(f"Fallback transcription strategy set to: {strategy_name}")
        return True
    
    def switch_strategy(self, new_strategy_name: str) -> bool:
        """
        Switch to a new primary strategy
        
        Args:
            new_strategy_name: Name of the new strategy
            
        Returns:
            True if successful, False otherwise
        """
        if self._strategy_lock:
            with self._strategy_lock:
                return self._switch_strategy_unsafe(new_strategy_name)
        else:
            return self._switch_strategy_unsafe(new_strategy_name)
    
    def _switch_strategy_unsafe(self, new_strategy_name: str) -> bool:
        """Switch strategy without locking (internal use)"""
        old_strategy_name = self._current_strategy_name
        
        if self._set_primary_strategy_unsafe(new_strategy_name):
            self.logger.info(f"Switched transcription strategy from {old_strategy_name} to {new_strategy_name}")
            return True
        else:
            self.logger.error(f"Failed to switch to strategy: {new_strategy_name}")
            return False
    
    def transcribe_with_fallback(self, audio_segment: AudioSegment) -> TranscriptionResult:
        """
        Transcribe audio with automatic fallback on failure
        
        Args:
            audio_segment: AudioSegment to transcribe
            
        Returns:
            TranscriptionResult with transcription and metadata
        """
        if not self._primary_strategy:
            raise TranscriptionError("No primary transcription strategy configured", "TranscriptionManager")
        
        start_time = time.time()
        
        # Try primary strategy first
        try:
            result = self._primary_strategy.transcribe(audio_segment)
            
            # Update performance stats
            self._update_performance_stats(result, start_time)
            
            # Check if transcription was successful
            if result.error_message is None and result.text:
                return result
            elif result.error_message is None:
                # Empty result but no error - this is valid (silence)
                return result
            else:
                # Primary strategy failed, try fallback
                self.logger.warning(f"Primary strategy failed: {result.error_message}")
                fallback_result = self._attempt_fallback(audio_segment, result)
                
                # Update performance stats for fallback
                if fallback_result.fallback_used:
                    self._update_performance_stats(fallback_result, start_time, is_fallback=True)
                
                return fallback_result
                
        except Exception as e:
            self.logger.error(f"Primary strategy exception: {e}")
            # Create error result and attempt fallback
            error_result = TranscriptionResult(
                text="",
                method_used=self._primary_strategy.get_name(),
                processing_time=time.time() - start_time,
                fallback_used=False,
                error_message=str(e)
            )
            
            # Update performance stats for error
            self._update_performance_stats(error_result, start_time)
            
            fallback_result = self._attempt_fallback(audio_segment, error_result)
            
            # Update performance stats for fallback
            if fallback_result.fallback_used:
                self._update_performance_stats(fallback_result, start_time, is_fallback=True)
            
            return fallback_result
    
    def _attempt_fallback(self, audio_segment: AudioSegment, primary_result: TranscriptionResult) -> TranscriptionResult:
        """Attempt fallback transcription"""
        from config import ENABLE_FALLBACK, FALLBACK_RETRY_LIMIT, FALLBACK_COOLDOWN_PERIOD
        
        if not ENABLE_FALLBACK or not self._fallback_strategy:
            self.logger.info("Fallback disabled or not configured")
            return primary_result
        
        fallback_name = self._fallback_strategy.get_name()
        primary_name = self._primary_strategy.get_name() if self._primary_strategy else "Unknown"
        
        # Check fallback retry limits
        if self._fallback_counts[fallback_name] >= FALLBACK_RETRY_LIMIT:
            last_fallback = self._last_fallback_time[fallback_name]
            if last_fallback:
                time_since_last = (datetime.now() - last_fallback).total_seconds()
                if time_since_last < FALLBACK_COOLDOWN_PERIOD:
                    self.logger.info(f"Fallback cooldown active for {fallback_name}")
                    return primary_result
                else:
                    # Reset fallback count after cooldown
                    self._fallback_counts[fallback_name] = 0
        
        try:
            self.logger.info(f"Attempting fallback transcription with {fallback_name}")
            
            # Notify about fallback activation
            self._notify_fallback_activation(primary_name, fallback_name, primary_result.error_message)
            
            fallback_result = self._fallback_strategy.transcribe(audio_segment)
            
            # Mark as fallback and update counters
            fallback_result.fallback_used = True
            self._fallback_counts[fallback_name] += 1
            self._last_fallback_time[fallback_name] = datetime.now()
            
            if fallback_result.error_message is None:
                self.logger.info(f"Fallback transcription successful with {fallback_name}")
                return fallback_result
            else:
                self.logger.warning(f"Fallback transcription also failed: {fallback_result.error_message}")
                return primary_result  # Return original error
                
        except Exception as e:
            self.logger.error(f"Fallback strategy exception: {e}")
            return primary_result  # Return original error
    
    def _notify_fallback_activation(self, from_method: str, to_method: str, reason: str):
        """Notify about fallback activation using exception notifier"""
        try:
            # Try to get exception notifier (it might not be available in all contexts)
            from exception_notifier import ExceptionNotifier
            notifier = ExceptionNotifier()
            notifier.notify_transcription_fallback(from_method, to_method, reason)
        except Exception as e:
            self.logger.debug(f"Could not notify fallback activation: {e}")
            # Don't fail the transcription process if notification fails
    
    def get_available_strategies(self) -> Dict[str, bool]:
        """Get list of available strategies"""
        return {name: strategy.is_available() for name, strategy in self._strategies.items()}
    
    def get_current_strategy_name(self) -> Optional[str]:
        """Get name of current primary strategy"""
        return self._current_strategy_name
    
    def get_strategy_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status of all strategies"""
        return {name: strategy.get_health_status() for name, strategy in self._strategies.items()}
    
    def cleanup(self):
        """Cleanup all strategies and manager resources"""
        try:
            # Cleanup all strategies
            for strategy in self._strategies.values():
                try:
                    strategy.cleanup()
                except Exception as e:
                    self.logger.warning(f"Error cleaning up strategy {strategy.get_name()}: {e}")
            
            # Clear strategy references
            self._strategies.clear()
            self._primary_strategy = None
            self._fallback_strategy = None
            self._current_strategy_name = None
            
            # Clear performance data to free memory
            self._performance_stats.clear()
            self._fallback_counts.clear()
            self._last_fallback_time.clear()
            
            # Force garbage collection
            import gc
            gc.collect()
            
            self.logger.info("TranscriptionManager cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during TranscriptionManager cleanup: {e}")
    
    def optimize_memory_usage(self):
        """Optimize memory usage by cleaning up old performance data"""
        try:
            # Limit recent performance history
            max_recent_entries = 50
            if len(self._performance_stats.get("recent_performance", [])) > max_recent_entries:
                self._performance_stats["recent_performance"] = self._performance_stats["recent_performance"][-max_recent_entries:]
                self.logger.debug(f"Trimmed performance history to {max_recent_entries} entries")
            
            # Reset fallback counts if they're very old
            from datetime import timedelta
            cutoff_time = datetime.now() - timedelta(hours=1)
            
            for strategy_name, last_time in list(self._last_fallback_time.items()):
                if last_time and last_time < cutoff_time:
                    self._fallback_counts[strategy_name] = 0
                    self._last_fallback_time[strategy_name] = None
                    self.logger.debug(f"Reset old fallback count for {strategy_name}")
            
            # Force garbage collection
            import gc
            gc.collect()
            
        except Exception as e:
            self.logger.warning(f"Error optimizing memory usage: {e}")
    
    def _update_performance_stats(self, result: TranscriptionResult, start_time: float, is_fallback: bool = False):
        """Update performance statistics"""
        try:
            total_time = time.time() - start_time
            method_name = result.method_used
            
            # Update global stats
            self._performance_stats["total_requests"] += 1
            self._performance_stats["total_processing_time"] += total_time
            
            if result.error_message is None:
                self._performance_stats["successful_requests"] += 1
            else:
                self._performance_stats["failed_requests"] += 1
            
            if is_fallback:
                self._performance_stats["fallback_requests"] += 1
            
            # Update strategy-specific stats
            if method_name not in self._performance_stats["strategy_stats"]:
                self._performance_stats["strategy_stats"][method_name] = {
                    "requests": 0,
                    "successful": 0,
                    "failed": 0,
                    "total_time": 0.0,
                    "avg_time": 0.0
                }
            
            strategy_stats = self._performance_stats["strategy_stats"][method_name]
            strategy_stats["requests"] += 1
            strategy_stats["total_time"] += result.processing_time
            
            if result.error_message is None:
                strategy_stats["successful"] += 1
            else:
                strategy_stats["failed"] += 1
            
            # Calculate average time
            if strategy_stats["requests"] > 0:
                strategy_stats["avg_time"] = strategy_stats["total_time"] / strategy_stats["requests"]
            
            # Update recent performance (rolling window)
            performance_entry = {
                "timestamp": datetime.now(),
                "method": method_name,
                "success": result.error_message is None,
                "processing_time": result.processing_time,
                "fallback": is_fallback
            }
            
            self._performance_stats["recent_performance"].append(performance_entry)
            
            # Keep only last 100 entries
            if len(self._performance_stats["recent_performance"]) > 100:
                self._performance_stats["recent_performance"].pop(0)
                
        except Exception as e:
            self.logger.warning(f"Error updating performance stats: {e}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get current performance statistics"""
        try:
            stats = self._performance_stats.copy()
            
            # Calculate overall averages
            if stats["total_requests"] > 0:
                stats["overall_avg_time"] = stats["total_processing_time"] / stats["total_requests"]
                stats["success_rate"] = stats["successful_requests"] / stats["total_requests"]
                stats["fallback_rate"] = stats["fallback_requests"] / stats["total_requests"]
            else:
                stats["overall_avg_time"] = 0.0
                stats["success_rate"] = 0.0
                stats["fallback_rate"] = 0.0
            
            # Calculate recent performance (last 10 requests)
            recent = stats["recent_performance"][-10:] if stats["recent_performance"] else []
            if recent:
                recent_success = sum(1 for r in recent if r["success"])
                recent_fallback = sum(1 for r in recent if r["fallback"])
                recent_avg_time = sum(r["processing_time"] for r in recent) / len(recent)
                
                stats["recent_success_rate"] = recent_success / len(recent)
                stats["recent_fallback_rate"] = recent_fallback / len(recent)
                stats["recent_avg_time"] = recent_avg_time
            else:
                stats["recent_success_rate"] = 0.0
                stats["recent_fallback_rate"] = 0.0
                stats["recent_avg_time"] = 0.0
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting performance stats: {e}")
            return {}
    
    def get_performance_summary(self) -> str:
        """Get a human-readable performance summary"""
        try:
            stats = self.get_performance_stats()
            
            if stats["total_requests"] == 0:
                return "No transcription requests processed yet"
            
            summary = f"Transcription Performance Summary:\n"
            summary += f"  Total Requests: {stats['total_requests']}\n"
            summary += f"  Success Rate: {stats['success_rate']:.1%}\n"
            summary += f"  Fallback Rate: {stats['fallback_rate']:.1%}\n"
            summary += f"  Average Time: {stats['overall_avg_time']:.2f}s\n"
            
            if stats["strategy_stats"]:
                summary += f"\nBy Method:\n"
                for method, method_stats in stats["strategy_stats"].items():
                    success_rate = method_stats["successful"] / method_stats["requests"] if method_stats["requests"] > 0 else 0
                    summary += f"  {method}: {method_stats['requests']} requests, {success_rate:.1%} success, {method_stats['avg_time']:.2f}s avg\n"
            
            return summary
            
        except Exception as e:
            self.logger.error(f"Error generating performance summary: {e}")
            return "Error generating performance summary"