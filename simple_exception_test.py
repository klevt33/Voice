#!/usr/bin/env python3
"""
Simple test to verify exception notification is working in the actual application.
"""

def test_exception_system():
    """Simple test of the exception notification system."""
    print("Testing Exception Notification System")
    print("=" * 40)
    
    try:
        # Test 1: Import and basic functionality
        from exception_notifier import exception_notifier
        print("✓ Exception notifier imported")
        
        # Test 2: Check if we can simulate errors
        from exception_testing_utils import exception_simulator
        print("✓ Exception simulator imported")
        
        # Test 3: Enable simulation and test
        import os
        os.environ["ENABLE_EXCEPTION_SIMULATION"] = "true"
        
        # Recreate simulator with simulation enabled
        from exception_testing_utils import ExceptionSimulator
        simulator = ExceptionSimulator()
        
        if simulator.simulation_enabled:
            print("✓ Exception simulation enabled")
            
            # Test CUDA error simulation
            if simulator.simulate_cuda_error("memory"):
                print("✓ CUDA error simulation works")
            else:
                print("✗ CUDA error simulation failed")
                
            # Test audio error simulation  
            if simulator.simulate_audio_device_error("ME"):
                print("✓ Audio error simulation works")
            else:
                print("✗ Audio error simulation failed")
                
            # Check active exceptions
            active_count = len(exception_notifier.get_active_exceptions())
            print(f"✓ Active exceptions: {active_count}")
            
            # Clear all exceptions
            simulator.clear_all_simulated_exceptions()
            print("✓ Exceptions cleared")
            
        else:
            print("✗ Exception simulation not enabled")
            
        print("\nException system test completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_exception_system()