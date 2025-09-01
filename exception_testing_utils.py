# exception_testing_utils.py
"""
Development and testing utilities for the exception notification system.
Provides tools for simulating exceptions and testing UI behavior.
"""

import os
import logging
import time
from typing import Optional, Dict, Any
from exception_notifier import exception_notifier

logger = logging.getLogger(__name__)

class ExceptionSimulator:
    """
    Utility class for simulating various types of exceptions during development and testing.
    """
    
    def __init__(self):
        self.simulation_enabled = self._check_simulation_enabled()
        if self.simulation_enabled:
            logger.info("Exception simulation enabled via environment variable")
    
    def _check_simulation_enabled(self) -> bool:
        """Check if exception simulation is enabled via environment variable."""
        return os.getenv("ENABLE_EXCEPTION_SIMULATION", "false").lower() in ("true", "1", "yes")
    
    def simulate_cuda_error(self, error_type: str = "memory") -> bool:
        """
        Simulate a CUDA error for testing purposes.
        
        Args:
            error_type: Type of CUDA error to simulate ("memory", "driver", "device", "generic")
            
        Returns:
            True if simulation was triggered, False if simulation is disabled
        """
        if not self.simulation_enabled:
            return False
        
        cuda_errors = {
            "memory": RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB (GPU 0; 8.00 GiB total capacity)"),
            "driver": RuntimeError("CUDA driver version is insufficient for CUDA runtime version"),
            "device": RuntimeError("CUDA error: device-side assert triggered"),
            "generic": RuntimeError("CUDA error: an illegal memory access was encountered")
        }
        
        error = cuda_errors.get(error_type, cuda_errors["generic"])
        exception_notifier.notify_exception("transcription", error, "error")
        
        logger.info(f"Simulated CUDA {error_type} error")
        return True
    
    def simulate_audio_device_error(self, source: str = "ME", error_type: str = "device_unavailable") -> bool:
        """
        Simulate an audio device error for testing purposes.
        
        Args:
            source: Audio source ("ME" or "OTHERS")
            error_type: Type of audio error to simulate
            
        Returns:
            True if simulation was triggered, False if simulation is disabled
        """
        if not self.simulation_enabled:
            return False
        
        audio_errors = {
            "device_unavailable": RuntimeError("errno -9996: Invalid device"),
            "host_error": RuntimeError("errno -9999: Unanticipated host error"),
            "stream_closed": RuntimeError("errno -9988: Stream closed"),
            "device_disconnected": RuntimeError("Device unavailable: microphone disconnected")
        }
        
        error = audio_errors.get(error_type, audio_errors["device_unavailable"])
        exception_notifier.notify_exception("audio_device", error, "warning", f"Audio Device Error - {source}")
        
        logger.info(f"Simulated audio {error_type} error for {source}")
        return True
    
    def simulate_audio_recording_error(self, source: str = "ME") -> bool:
        """
        Simulate an audio recording error for testing purposes.
        
        Args:
            source: Audio source ("ME" or "OTHERS")
            
        Returns:
            True if simulation was triggered, False if simulation is disabled
        """
        if not self.simulation_enabled:
            return False
        
        error = RuntimeError("Error reading from audio stream")
        exception_notifier.notify_exception("audio_recording", error, "warning", f"Audio Recording Error - {source}")
        
        logger.info(f"Simulated audio recording error for {source}")
        return True
    
    def simulate_transcription_error(self, error_type: str = "generic") -> bool:
        """
        Simulate a transcription error for testing purposes.
        
        Args:
            error_type: Type of transcription error to simulate
            
        Returns:
            True if simulation was triggered, False if simulation is disabled
        """
        if not self.simulation_enabled:
            return False
        
        transcription_errors = {
            "generic": ValueError("Error processing audio data"),
            "format": RuntimeError("Unsupported audio format"),
            "model": RuntimeError("Model loading failed"),
            "timeout": TimeoutError("Transcription timeout")
        }
        
        error = transcription_errors.get(error_type, transcription_errors["generic"])
        exception_notifier.notify_exception("transcription", error, "error")
        
        logger.info(f"Simulated transcription {error_type} error")
        return True
    
    def simulate_rapid_exceptions(self, count: int = 5, delay: float = 0.1) -> bool:
        """
        Simulate rapid repeated exceptions to test deduplication.
        
        Args:
            count: Number of exceptions to simulate
            delay: Delay between exceptions in seconds
            
        Returns:
            True if simulation was triggered, False if simulation is disabled
        """
        if not self.simulation_enabled:
            return False
        
        error = RuntimeError("Rapid exception test")
        
        for i in range(count):
            exception_notifier.notify_exception("test_rapid", error, "error", "Rapid Exception Test")
            if delay > 0:
                time.sleep(delay)
        
        logger.info(f"Simulated {count} rapid exceptions with {delay}s delay")
        return True
    
    def clear_all_simulated_exceptions(self) -> bool:
        """
        Clear all simulated exceptions.
        
        Returns:
            True if simulation is enabled, False otherwise
        """
        if not self.simulation_enabled:
            return False
        
        sources = ["transcription", "audio_device", "audio_recording", "test_rapid"]
        for source in sources:
            exception_notifier.clear_exception_status(source)
        
        logger.info("Cleared all simulated exceptions")
        return True

class ExceptionTestingHelper:
    """
    Helper class for testing exception notification behavior.
    """
    
    @staticmethod
    def get_active_exception_count() -> int:
        """Get the number of currently active exceptions."""
        return len(exception_notifier.get_active_exceptions())
    
    @staticmethod
    def get_active_exceptions_by_source() -> Dict[str, int]:
        """Get active exceptions grouped by source."""
        active = exception_notifier.get_active_exceptions()
        by_source = {}
        
        for notification in active.values():
            source = notification.source
            if source not in by_source:
                by_source[source] = 0
            by_source[source] += 1
        
        return by_source
    
    @staticmethod
    def wait_for_exception_count(expected_count: int, timeout: float = 5.0) -> bool:
        """
        Wait for the active exception count to reach the expected value.
        
        Args:
            expected_count: Expected number of active exceptions
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if expected count was reached, False if timeout
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if ExceptionTestingHelper.get_active_exception_count() == expected_count:
                return True
            time.sleep(0.1)
        
        return False
    
    @staticmethod
    def wait_for_source_exception(source: str, should_exist: bool = True, timeout: float = 5.0) -> bool:
        """
        Wait for an exception from a specific source to exist or not exist.
        
        Args:
            source: Source to check for
            should_exist: Whether the exception should exist (True) or not exist (False)
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if condition was met, False if timeout
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            exists = exception_notifier.is_exception_active(source)
            if exists == should_exist:
                return True
            time.sleep(0.1)
        
        return False
    
    @staticmethod
    def print_active_exceptions():
        """Print all currently active exceptions for debugging."""
        active = exception_notifier.get_active_exceptions()
        
        if not active:
            print("No active exceptions")
            return
        
        print(f"Active exceptions ({len(active)}):")
        for i, (hash_key, notification) in enumerate(active.items(), 1):
            print(f"  {i}. Source: {notification.source}")
            print(f"     Message: {notification.user_message}")
            print(f"     Count: {notification.count}")
            print(f"     Severity: {notification.severity.value}")
            print(f"     Timestamp: {notification.timestamp}")
            print()

# Global instance for easy access
exception_simulator = ExceptionSimulator()

def enable_exception_simulation():
    """Enable exception simulation programmatically."""
    os.environ["ENABLE_EXCEPTION_SIMULATION"] = "true"
    global exception_simulator
    exception_simulator = ExceptionSimulator()
    logger.info("Exception simulation enabled programmatically")

def disable_exception_simulation():
    """Disable exception simulation programmatically."""
    os.environ["ENABLE_EXCEPTION_SIMULATION"] = "false"
    global exception_simulator
    exception_simulator = ExceptionSimulator()
    logger.info("Exception simulation disabled programmatically")

# Convenience functions for common testing scenarios
def test_cuda_memory_error():
    """Quick test for CUDA memory error."""
    return exception_simulator.simulate_cuda_error("memory")

def test_audio_device_disconnection():
    """Quick test for audio device disconnection."""
    return exception_simulator.simulate_audio_device_error("ME", "device_disconnected")

def test_exception_deduplication():
    """Quick test for exception deduplication."""
    return exception_simulator.simulate_rapid_exceptions(5, 0.1)

def test_recovery_scenario():
    """Test a complete error and recovery scenario."""
    if not exception_simulator.simulation_enabled:
        return False
    
    # Simulate error
    exception_simulator.simulate_cuda_error("memory")
    
    # Wait a moment
    time.sleep(1)
    
    # Simulate recovery
    exception_notifier.clear_exception_status("transcription")
    
    logger.info("Simulated complete error and recovery scenario")
    return True

if __name__ == "__main__":
    # Example usage when run directly
    print("Exception Testing Utilities")
    print("=" * 40)
    
    # Check if simulation is enabled
    if exception_simulator.simulation_enabled:
        print("Exception simulation is ENABLED")
        print("\nAvailable test functions:")
        print("- test_cuda_memory_error()")
        print("- test_audio_device_disconnection()")
        print("- test_exception_deduplication()")
        print("- test_recovery_scenario()")
        print("\nHelper functions:")
        print("- ExceptionTestingHelper.print_active_exceptions()")
        print("- ExceptionTestingHelper.get_active_exception_count()")
        
        # Run a quick demo
        print("\nRunning quick demo...")
        test_cuda_memory_error()
        time.sleep(0.5)
        test_audio_device_disconnection()
        time.sleep(0.5)
        
        print(f"\nActive exceptions: {ExceptionTestingHelper.get_active_exception_count()}")
        ExceptionTestingHelper.print_active_exceptions()
        
        # Clean up
        exception_simulator.clear_all_simulated_exceptions()
        print("Demo complete - exceptions cleared")
        
    else:
        print("Exception simulation is DISABLED")
        print("Set environment variable ENABLE_EXCEPTION_SIMULATION=true to enable")
        print("Or call enable_exception_simulation() programmatically")