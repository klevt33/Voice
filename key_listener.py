import sys
import time
import logging
import keyboard
from typing import Dict, Any, Optional, Callable

# Configure logging
logger = logging.getLogger(__name__)

class KeyboardController:
    """
    A class to handle keyboard controls for pausing/resuming and exiting the application.
    """
    def __init__(self, pause_state: Dict[str, bool], run_state: Dict[str, bool], 
                 exit_handler: Optional[Callable] = None):
        """
        Initialize the keyboard controller.
        
        Args:
            pause_state: Dictionary with pause state flags
            run_state: Dictionary with running state flags
            exit_handler: Optional callback function to run when exiting
        """
        self.pause_state = pause_state
        self.run_state = run_state
        self.exit_handler = exit_handler
        self.status_message = ""
        self.listener_thread = None
        
    def start(self):
        """Register key handlers and show initial status"""
        # Register key event handlers
        keyboard.on_press_key("space", self._on_space_press)
        keyboard.on_press_key("esc", self._on_esc_press)
        
        # Print initial status
        self.status_message = f"\rStatus: RUNNING (Press SPACE to toggle, ESC to exit)"
        sys.stdout.write(self.status_message)
        sys.stdout.flush()
        
        logger.info("Keyboard controller started")
        
    def stop(self):
        """Clean up key handlers"""
        try:
            keyboard.unhook_all()
            logger.info("Keyboard controller stopped")
        except Exception as e:
            logger.error(f"Error stopping keyboard controller: {e}")
            
    def _on_space_press(self, e):
        """Handler for spacebar press - toggles pause state"""
        if not self.run_state["active"]:
            return
        
        # Toggle the pause state
        self.pause_state["all"] = not self.pause_state["all"]
        status = "PAUSED" if self.pause_state["all"] else "RUNNING"
        
        # Clear previous status line and print new status
        if self.status_message:
            sys.stdout.write("\r" + " " * len(self.status_message))
        self.status_message = f"\rStatus: {status} (Press SPACE to toggle, ESC to exit)"
        sys.stdout.write(self.status_message)
        sys.stdout.flush()
        
        logger.info(f"Processing {'paused' if self.pause_state['all'] else 'resumed'}")
    
    def _on_esc_press(self, e):
        """Handler for ESC press - triggers application exit"""
        if not self.run_state["active"]:
            return
        print("\nExiting application...")
        self.run_state["active"] = False
        
        # Call exit handler if provided
        if self.exit_handler:
            self.exit_handler(None, None)

def keyboard_listener_thread(pause_state: Dict[str, bool], run_state: Dict[str, bool], 
                           exit_handler: Optional[Callable] = None) -> None:
    """
    Thread function to handle keyboard shortcuts for controlling the application.
    
    Args:
        pause_state: Dictionary with pause state flags
        run_state: Dictionary with running state flags
        exit_handler: Optional callback function to run when exiting
    """
    logger.info("Keyboard listener started. Press SPACE to toggle pause/resume, ESC to exit")
    print("\nControls:")
    print("  SPACE - Toggle pause/resume all processing")
    print("  ESC   - Exit application")
    
    # Create and start the keyboard controller
    controller = KeyboardController(pause_state, run_state, exit_handler)
    controller.start()
    
    try:
        # Keep thread alive until program exits
        while run_state["active"]:
            time.sleep(0.1)
    finally:
        controller.stop()