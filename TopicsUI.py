# TopicsUI.py
import tkinter as tk
from datetime import datetime
import queue
import threading
import logging
from dataclasses import dataclass
from typing import List, Optional
import pyperclip

from ui_view import UIView
from topic_storage import TopicStorageManager
from config import TOPIC_STORAGE_FOLDER

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("transcription.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class Topic:
    text: str
    timestamp: datetime
    source: str  # Either "ME" or "OTHERS"
    selected: bool = False
    submitted: bool = False
    
    def get_display_text(self):
        source_tag = f"[{self.source}]"
        return f"[{self.timestamp.strftime('%H:%M')}] {source_tag} {self.text}"

class UIController:
    """
    Manages the application logic for the UI, acting as a controller.
    It handles user interactions and updates the view.
    """
    def __init__(self, root, app_controller):
        self.root = root
        self.app_controller = app_controller
        self.topics: List[Topic] = []
        self.topic_queue = queue.Queue()
        self.last_clicked_index = -1  # Track which topic was clicked last
        
        # Initialize topic storage manager
        self.storage_manager = TopicStorageManager(TOPIC_STORAGE_FOLDER)
        
        # The View is created and managed by the controller
        self.view = UIView(root, self)
        self.view.listen_var.set(False)
        
        self.processing = True
        self.queue_thread = threading.Thread(target=self.process_topic_queue, daemon=True)
        self.queue_thread.start()
        
        # Initialize transcription method UI
        self.root.after(500, self.initialize_transcription_method_ui)  # Delay to allow transcription system to initialize
        
        self.root.after(100, self.update_ui_loop)

    def on_auto_submit_change(self, selected_mode: str):
        logger.info(f"UI Auto-Submit mode changed to: {selected_mode}")
        self.app_controller.set_auto_submit_mode(selected_mode)
    
    def on_transcription_method_change(self):
        """Handle transcription method checkbox change"""
        try:
            use_api = self.view.get_transcription_method_preference()
            method_name = "api" if use_api else "local"
            
            logger.info(f"UI Transcription method change requested: {method_name}")
            
            # Import transcription functions
            from transcription import switch_transcription_method, get_current_transcription_method
            
            # Attempt to switch method
            success = switch_transcription_method(method_name)
            
            if success:
                current_method = get_current_transcription_method()
                logger.info(f"Successfully switched transcription method to: {current_method}")
                
                # Update transcription status
                self.view.update_transcription_status(current_method, False, f"Switched to {current_method}")
                
                # Update UI to reflect actual state
                self._update_transcription_method_ui()
            else:
                logger.error(f"Failed to switch transcription method to: {method_name}")
                
                # Revert checkbox to previous state
                self.view.transcription_method_var.set(not use_api)
                
                # Show error message
                self.view.show_transcription_error("method_switch", f"Failed to switch to {method_name} transcription")
                
        except Exception as e:
            logger.error(f"Error changing transcription method: {e}")
            
            # Revert checkbox and show error
            use_api = self.view.get_transcription_method_preference()
            self.view.transcription_method_var.set(not use_api)
            self.view.show_transcription_error("exception", f"Transcription method change failed: {e}")
    
    def _update_transcription_method_ui(self):
        """Update UI to reflect current transcription method state"""
        try:
            from transcription import get_transcription_capabilities, get_current_transcription_method
            
            capabilities = get_transcription_capabilities()
            current_method = get_current_transcription_method()
            
            # Update the transcription method control
            self.view.update_transcription_method_control(
                gpu_available=capabilities["gpu_available"],
                api_available=capabilities["api_available"],
                current_method=current_method
            )
            
        except Exception as e:
            logger.error(f"Error updating transcription method UI: {e}")
    
    def initialize_transcription_method_ui(self):
        """Initialize transcription method UI based on current capabilities"""
        try:
            self._update_transcription_method_ui()
            self._update_transcription_status_display()
        except Exception as e:
            logger.error(f"Error initializing transcription method UI: {e}")
    
    def _update_transcription_status_display(self):
        """Update the status display with current transcription method"""
        try:
            from transcription import get_current_transcription_method, get_transcription_health_status
            
            current_method = get_current_transcription_method()
            if current_method:
                # Check if fallback is active by examining health status
                health_status = get_transcription_health_status()
                is_fallback = False
                
                # Simple heuristic: if we have multiple strategies and errors on the primary
                if len(health_status) > 1:
                    for strategy_name, status in health_status.items():
                        if strategy_name == current_method and status.get("error_count", 0) > 0:
                            is_fallback = True
                            break
                
                self.view.update_transcription_status(current_method, is_fallback)
            
        except Exception as e:
            logger.error(f"Error updating transcription status display: {e}")
    
    def toggle_listening(self, *args):
        if self.view.listen_var.get():
            # Start audio monitoring and storage session
            try:
                storage_started = self.storage_manager.start_session()
                if not storage_started:
                    logger.warning("Failed to start storage session, but continuing with audio monitoring")
            except Exception as e:
                logger.error(f"Error starting storage session: {e}")
            
            self.app_controller.start_listening()
        else:
            # Stop audio monitoring and end storage session
            self.app_controller.stop_listening()
            try:
                self.storage_manager.end_session()
            except Exception as e:
                logger.error(f"Error ending storage session: {e}")
    
    def set_listening_state(self, is_listening: bool):
        """
        Programmatically set the listening toggle state without triggering callbacks.
        Used during audio reconnection to reflect state changes.
        """
        # Get all current traces and remove them temporarily
        traces = self.view.listen_var.trace_info()
        for trace in traces:
            if trace[1] == "write":
                self.view.listen_var.trace_remove("write", trace[2])
        
        # Set the value
        self.view.listen_var.set(is_listening)
        
        # Re-add the trace
        self.view.listen_var.trace_add("write", self.toggle_listening)

    def request_new_ai_thread_ui(self):
        logger.info("UI 'New Thread' button clicked.")
        context_from_ui = self.view.context_text.get(1.0, tk.END).strip()
        self.update_browser_status("info", "Status: Starting new AI thread...")
        self.app_controller.request_new_ai_thread(context_text=context_from_ui)

    def request_manual_reconnection(self):
        logger.info("UI 'Reconnect' button clicked.")
        self.update_browser_status("info", "Status: Manual reconnection requested...")
        
        # Note: Dropdown doesn't need to be disabled as it resets after selection
        
        # Request manual reconnection from app controller
        self.app_controller.request_manual_reconnection()

    def request_manual_audio_reconnection(self):
        logger.info("UI 'Reconnect Audio' button clicked.")
        self.update_browser_status("info", "Status: Manual audio reconnection requested...")
        
        # Note: Dropdown doesn't need to be disabled as it resets after selection
        
        # Request manual audio reconnection from app controller
        self.app_controller.request_manual_audio_reconnection()

    def on_reconnect_selection(self, selected_option: str):
        """Handle reconnect dropdown selection."""
        if selected_option == "Browser":
            logger.info("UI Reconnect dropdown: Browser selected")
            self.request_manual_reconnection()
        elif selected_option == "Audio":
            logger.info("UI Reconnect dropdown: Audio selected")
            self.request_manual_audio_reconnection()
        elif selected_option == "Both":
            logger.info("UI Reconnect dropdown: Both selected")
            self.update_browser_status("info", "Status: Reconnecting browser and audio...")
            self.request_manual_reconnection()
            self.request_manual_audio_reconnection()
        
        # Reset dropdown to default after selection
        self.view.reconnect_var.set("Reconnect")

    def add_topic_to_queue(self, topic: Topic):
        self.topic_queue.put(topic)

    def process_topic_queue(self):
        while self.processing:
            try:
                topic = self.topic_queue.get(timeout=0.1)
                self.topics.append(topic)
                
                # Store topic to persistent storage
                try:
                    storage_success = self.storage_manager.store_topic(topic)
                    if not storage_success:
                        logger.warning(f"Failed to store topic to file: {topic.text[:50]}...")
                except Exception as e:
                    logger.error(f"Error storing topic to file: {e}")
                
                logger.info(f"Added new topic from {topic.source}: {topic.text[:50]}...")
                self.topic_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"Error processing topic queue: {e}")

    def update_ui_loop(self):
        yview = self.view.topic_listbox.yview()
        self.view.topic_listbox.delete(0, tk.END)
        
        for i, topic in enumerate(self.topics):
            self.view.topic_listbox.insert(tk.END, topic.get_display_text())
            
            # Determine if we should show visual indication for submitted topics
            show_submitted_indication = not self.get_delete_submitted_preference() and topic.submitted
            
            # Apply color based on selection state, last-clicked status, and submitted status
            if i == self.last_clicked_index:
                # Last clicked topic gets special highlighting
                if topic.selected:
                    # Last clicked + selected = darker blue
                    bg_color = '#a0a0ff'
                else:
                    # Last clicked + deselected = very light blue
                    bg_color = '#f0f0ff'
                
                # Apply submitted text color if needed
                if show_submitted_indication:
                    self.view.topic_listbox.itemconfig(i, {'bg': bg_color, 'fg': '#808080'})
                else:
                    self.view.topic_listbox.itemconfig(i, {'bg': bg_color})
                    
            elif topic.selected:
                # Regular selected = normal blue
                if show_submitted_indication:
                    self.view.topic_listbox.itemconfig(i, {'bg': '#d0d0ff', 'fg': '#808080'})
                else:
                    self.view.topic_listbox.itemconfig(i, {'bg': '#d0d0ff'})
            else:
                # Deselected topics - apply submitted indication if needed
                if show_submitted_indication:
                    self.view.topic_listbox.itemconfig(i, {'fg': '#808080'})
                # Otherwise use default white background and black text (no itemconfig needed)
            
            # Note: Removed selection_set calls to prevent overriding custom colors
        
        if self.view.topic_listbox.size() > 0 and yview != (0.0, 1.0):
            try:
                self.view.topic_listbox.yview_moveto(yview[0])
            except tk.TclError:
                pass
        
        self.root.after(100, self.update_ui_loop)

    def toggle_selection(self, event):
        try:
            idx = self.view.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                self.topics[idx].selected = not self.topics[idx].selected
                self.last_clicked_index = idx  # Track which topic was clicked last
                self._update_full_text_display(idx)
        except tk.TclError:
            pass

    def delete_topic(self, event):
        try:
            idx = self.view.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                # Check if we're deleting the last clicked topic and if it was selected
                if self.last_clicked_index == idx:
                    # Only reset if the last clicked topic was selected (being deleted)
                    # If it was deselected, we keep the last_clicked_index but it will be invalid
                    if self.topics[idx].selected:
                        self.last_clicked_index = -1
                        self.clear_full_text_display()
                    # If deselected, we'll adjust the index below
                elif self.last_clicked_index > idx:
                    self.last_clicked_index -= 1  # Adjust index if deletion affects it
                
                del self.topics[idx]
                
                # Final check: if last_clicked_index is now out of bounds, reset it
                if self.last_clicked_index >= len(self.topics):
                    self.last_clicked_index = -1
                    self.clear_full_text_display()
        except tk.TclError:
            pass

    def show_full_topic(self, event):
        try:
            selected_indices = self.view.topic_listbox.curselection()
            if selected_indices:
                self._update_full_text_display(selected_indices[0])
        except tk.TclError:
            pass

    def _update_full_text_display(self, idx):
        if 0 <= idx < len(self.topics):
            self.view.full_text.config(state="normal")
            self.view.full_text.delete(1.0, tk.END)
            self.view.full_text.insert(tk.END, self.topics[idx].text)
            self.view.full_text.config(state="disabled")

    def select_topics(self, select_all=True):
        for topic in self.topics:
            topic.selected = select_all
        # Keep last clicked topic - its color will automatically adjust based on new selection state
        # (Dark blue for Select All, very light blue for Deselect All)

    def delete_topics(self, selected_only=True):
        # Check if last clicked topic will be deleted
        should_reset_last_clicked = False
        last_clicked_topic = None
        
        if 0 <= self.last_clicked_index < len(self.topics):
            last_clicked_topic = self.topics[self.last_clicked_index]
            if selected_only:
                # Only reset if last clicked topic was selected (being deleted)
                should_reset_last_clicked = last_clicked_topic.selected
            else:
                # Delete All - always reset
                should_reset_last_clicked = True
        
        if selected_only:
            self.topics = [t for t in self.topics if not t.selected]
        else:
            self.topics = []
        
        # Apply reset logic or adjust index
        if should_reset_last_clicked:
            self.last_clicked_index = -1
            self.clear_full_text_display()
        elif last_clicked_topic is not None:
            # Find the new index of the last clicked topic
            try:
                self.last_clicked_index = self.topics.index(last_clicked_topic)
            except ValueError:
                # Topic not found (shouldn't happen, but safety check)
                self.last_clicked_index = -1
                self.clear_full_text_display()

    def submit_selected_topics(self, select_all_override=False):
        context = self.view.context_text.get(1.0, tk.END).strip()
        
        selected_topic_objects = list(self.topics) if select_all_override else [t for t in self.topics if t.selected]
        if not selected_topic_objects:
            self.update_browser_status("warning", "Status: No topics to submit.")
            return

        messages = [f"[CONTEXT] {context}"] if context else []
        messages.extend([f"[{t.source}] {t.text}" for t in selected_topic_objects])
        
        self.app_controller.submit_topics("\n".join(messages), selected_topic_objects)
        self.update_browser_status("info", f"Status: Submitted {len(selected_topic_objects)} topics...")

    def submit_all_topics(self):
        self.submit_selected_topics(select_all_override=True)

    def _format_topic_for_copy(self, topic: Topic, keep_prefix: bool) -> str:
        """Format a topic for copying based on prefix preference."""
        if keep_prefix:
            return f"[{topic.source}] {topic.text}"
        else:
            return topic.text

    def copy_selected_topics(self, select_all_override=False):
        context = self.view.context_text.get(1.0, tk.END).strip()
        
        selected_topic_objects = list(self.topics) if select_all_override else [t for t in self.topics if t.selected]
        if not selected_topic_objects:
            self.update_browser_status("warning", "Status: No topics to copy.")
            return

        keep_prefix = self.view.get_keep_prefix_state()
        
        messages = [f"[CONTEXT] {context}"] if context else []
        messages.extend([self._format_topic_for_copy(t, keep_prefix) for t in selected_topic_objects])
        
        consolidated_text = "\n".join(messages)
        pyperclip.copy(consolidated_text)
        self.update_browser_status("success", f"Status: Copied {len(selected_topic_objects)} topics to clipboard.")

    def copy_all_topics(self):
        self.copy_selected_topics(select_all_override=True)

    def clear_successfully_submitted_topics(self, submitted_topics: List[Topic]):
        if not submitted_topics:
            return
        
        delete_submitted = self.get_delete_submitted_preference()
        submitted_ids = {id(t) for t in submitted_topics}
        
        if not delete_submitted:
            # Mark topics as submitted instead of removing them
            for topic in self.topics:
                if id(topic) in submitted_ids:
                    topic.submitted = True
            logger.info(f"Marked {len(submitted_topics)} topics as submitted in UI.")
        else:
            # Delete submitted behavior: remove submitted topics
            # Check if the last clicked topic is being removed and if it was selected
            should_reset_last_clicked = False
            last_clicked_topic = None
            
            if 0 <= self.last_clicked_index < len(self.topics):
                last_clicked_topic = self.topics[self.last_clicked_index]
                last_clicked_topic_id = id(last_clicked_topic)
                if last_clicked_topic_id in submitted_ids:
                    # Only reset if the last clicked topic was selected (being submitted)
                    should_reset_last_clicked = last_clicked_topic.selected
            
            # Remove submitted topics
            self.topics = [t for t in self.topics if id(t) not in submitted_ids]
            
            # Apply reset logic or adjust index
            if should_reset_last_clicked:
                self.last_clicked_index = -1
                self.clear_full_text_display()
            elif last_clicked_topic is not None and id(last_clicked_topic) not in submitted_ids:
                # Find the new index of the last clicked topic (if it wasn't submitted)
                try:
                    self.last_clicked_index = self.topics.index(last_clicked_topic)
                except ValueError:
                    # Topic not found (shouldn't happen, but safety check)
                    self.last_clicked_index = -1
                    self.clear_full_text_display()
            elif self.last_clicked_index >= len(self.topics):
                # Index out of bounds
                self.last_clicked_index = -1
                self.clear_full_text_display()
            
            logger.info(f"Cleared {len(submitted_topics)} submitted topics from UI.")

    def clear_full_text_display(self):
        self.view.full_text.config(state="normal")
        self.view.full_text.delete(1.0, tk.END)
        self.view.full_text.config(state="disabled")

    def update_browser_status(self, status_key: str, custom_message: Optional[str] = None):
        self.view.update_browser_status(status_key, custom_message)
        level = "warning" if status_key in ["error", "browser_human_verification", "warning", "browser_input_unavailable"] else "info"
        logger.log(logging.getLevelName(level.upper()), f"UI Status Update ({status_key}): {custom_message or self.view.status_colors.get(status_key, (None, ''))[1]}")

    def get_delete_submitted_preference(self) -> bool:
        """Return the current state of the delete submitted checkbox."""
        return self.view.delete_submitted_var.get()

    def on_closing(self):
        logger.info("UIController: on_closing called.")
        self.processing = False
        
        # Ensure storage session is properly closed
        try:
            self.storage_manager.end_session()
        except Exception as e:
            logger.error(f"Error closing storage session during shutdown: {e}")
        
        self.app_controller.on_closing_ui_initiated()