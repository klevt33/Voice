# TopicsUI.py
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime
import queue
import threading
import logging
from dataclasses import dataclass
from typing import List, Optional

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
    
    def get_display_text(self):
        source_tag = f"[{self.source}]"
        return f"[{self.timestamp.strftime('%H:%M')}] {source_tag} {self.text}"

class TopicProcessor:
    def __init__(self, root, app_controller, start_listening_callback, stop_listening_callback, submit_topics_callback): # Added app_controller
        self.root = root
        self.root.title("Audio Transcription Processor")
        self.root.geometry("900x650") # Slightly increased height for status bar
        self.topics: List[Topic] = [] # Type hint
        self.topic_queue = queue.Queue()
        
        self.app_controller = app_controller # Store reference to AudioToChat instance
        self.start_listening_callback = start_listening_callback
        self.stop_listening_callback = stop_listening_callback
        self.submit_topics_callback = submit_topics_callback
        
        self.create_widgets()
        self.listen_var.set(False)
        
        self.processing = True
        self.queue_thread = threading.Thread(target=self.process_queue, daemon=True)
        self.queue_thread.start()
        
        self.root.after(100, self.update_ui)
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        list_frame = ttk.LabelFrame(main_frame, text="Topics", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # --- TOP BUTTON AREA FRAME (Parent for left and right button groups) ---
        top_button_area_frame = ttk.Frame(list_frame)
        top_button_area_frame.pack(fill=tk.X, padx=5, pady=5)

        # --- LEFT BUTTONS FRAME (Topic/selection management) ---
        left_buttons_frame = ttk.Frame(top_button_area_frame)
        left_buttons_frame.pack(side=tk.LEFT, anchor=tk.W) # Anchor to West (left)

        ttk.Button(left_buttons_frame, text="Select All", command=lambda: self.select_topics(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons_frame, text="Deselect All", command=lambda: self.select_topics(False)).pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons_frame, text="Delete Selection", command=lambda: self.delete_topics(selected_only=True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons_frame, text="Delete All", command=lambda: self.delete_topics(selected_only=False)).pack(side=tk.LEFT, padx=2)
        
        # --- RIGHT BUTTONS FRAME (Listen toggle and New Thread) ---
        right_buttons_frame = ttk.Frame(top_button_area_frame)
        right_buttons_frame.pack(side=tk.RIGHT, anchor=tk.E) # Anchor to East (right)

        # Order: New Thread button first, then Listen toggle
        ttk.Button(right_buttons_frame, text="New Thread", command=self.request_new_ai_thread_ui).pack(side=tk.LEFT, padx=(0, 5)) 
        
        self.listen_var = tk.BooleanVar(value=False)
        self.listen_var.trace_add("write", self.toggle_listening)
        self.create_toggle_switch(right_buttons_frame, "Listen", self.listen_var).pack(side=tk.LEFT, padx=5) # Listen toggle packs to the left within right_buttons_frame
        
        # --- Topic listbox with scrollbar (as before) ---
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.topic_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE, activestyle='none', 
                                        height=15, font=('TkDefaultFont', 10), 
                                        yscrollcommand=scrollbar.set)
        self.topic_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.topic_listbox.yview)
        
        self.topic_listbox.bind("<<ListboxSelect>>", self.show_full_topic)
        self.topic_listbox.bind("<ButtonRelease-1>", self.toggle_selection)
        self.topic_listbox.bind("<ButtonRelease-3>", self.delete_topic)

        # --- Full Topic Text section (as before) ---
        text_frame = ttk.LabelFrame(main_frame, text="Full Topic Text", padding="5")
        text_frame.pack(fill=tk.X, expand=False, pady=(0, 5))
        
        self.full_text = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, height=3, state="disabled")
        self.full_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # --- Context section (as before) ---
        context_frame = ttk.LabelFrame(main_frame, text="Context", padding="5")
        context_frame.pack(fill=tk.X, expand=False, pady=(0,5))
        
        self.context_text = scrolledtext.ScrolledText(context_frame, wrap=tk.WORD, height=2)
        self.context_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # --- SUBMIT BUTTONS FRAME (Centered) ---
        submit_buttons_main_frame = ttk.Frame(main_frame)
        # To center this frame that holds the buttons, we can pack it without fill/expand if its parent (main_frame) allows.
        # However, main_frame is set to fill and expand.
        # A common way to center a smaller group of widgets is to pack them into a frame,
        # and then pack that frame with appropriate options, or use grid's columnconfigure weight.
        # For pack, if we want it centered horizontally:
        submit_buttons_main_frame.pack(pady=5) # Default pack centers if no side is given and not fill/expand

        ttk.Button(submit_buttons_main_frame, text="Submit Selected", command=self.submit_selected_topics).pack(side=tk.LEFT, padx=5)
        ttk.Button(submit_buttons_main_frame, text="Submit All", command=self.submit_all_topics).pack(side=tk.LEFT, padx=5)

        # --- Status Bar (as before) ---
        status_bar_frame = ttk.Frame(main_frame, relief=tk.SUNKEN, padding="2 2 2 2")
        status_bar_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5,0))

        self.status_colors = { # As defined previously
            "default": ("gray", "Status: Initializing..."),
            "browser_ready": ("green", "AI Ready"),
            "browser_input_unavailable": ("#FF8C00", "AI Input Unavailable"), 
            "browser_human_verification": ("red", "AI Human Verification!"),
            "info": ("blue", "Info"),
            "success": ("green", "Success"),
            "warning": ("#FF8C00", "Warning"), 
            "error": ("red", "Error")
        }
        
        self.browser_status_indicator_label = ttk.Label(status_bar_frame, text="●", font=("TkDefaultFont", 12, "bold"))
        self.browser_status_indicator_label.pack(side=tk.LEFT, padx=(5, 2))
        
        self.status_message_label = ttk.Label(status_bar_frame, text="")
        self.status_message_label.pack(side=tk.LEFT, padx=(2, 5), fill=tk.X, expand=True)

        self.update_browser_status("default")
    
    def update_browser_status(self, status_key: str, custom_message: Optional[str] = None):
        """Updates the status bar indicator color and message."""
        color, default_message = self.status_colors.get(status_key, ("gray", "Status: Unknown"))
        
        message_to_display = custom_message if custom_message is not None else default_message
        
        self.browser_status_indicator_label.config(foreground=color)
        self.status_message_label.config(text=message_to_display, foreground=color) # Also color the text for emphasis
        
        if status_key in ["error", "browser_human_verification", "warning", "browser_input_unavailable"]:
            logger.warning(f"UI Status Update ({status_key}): {message_to_display}")
        else:
            logger.info(f"UI Status Update ({status_key}): {message_to_display}")

    def request_new_ai_thread_ui(self):
        logger.info("UI 'New Thread' button clicked.")
        if self.app_controller and hasattr(self.app_controller, 'request_new_ai_thread'):
            self.update_browser_status("info", "Status: Starting new AI thread...")
            self.app_controller.request_new_ai_thread()
        else:
            self.update_browser_status("error", "Error: New thread function not available.")

    def create_toggle_switch(self, parent, text, variable):
        frame = ttk.Frame(parent)
        
        self.toggle_button = tk.Label(frame, 
                                    width=6, 
                                    text="ON",
                                    font=("TkDefaultFont", 9, "bold"),
                                    fg="white",
                                    bg="#0b5394",
                                    padx=2,
                                    pady=2,
                                    relief="raised",
                                    bd=1)
        self.toggle_button.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Label(frame, text=text).pack(side=tk.LEFT)
        
        def update_toggle(*args):
            state = variable.get()
            self.toggle_button.config(
                text="ON" if state else "OFF",
                bg="#0b5394" if state else "#666666",
                fg="white"
            )
        
        # Store original colors for hover effect
        def on_enter(e):
            current_bg = self.toggle_button.cget("bg")
            # Brighten the current color slightly
            if current_bg == "#0b5394":  # Blue (ON)
                self.toggle_button.config(bg="#1a64a5")  # Lighter blue
            else:  # Gray (OFF)
                self.toggle_button.config(bg="#777777")  # Lighter gray
        
        def on_leave(e):
            # Restore original color based on state
            update_toggle()
        
        update_toggle()
        self.toggle_button.bind("<Button-1>", lambda e: [variable.set(not variable.get())])
        self.toggle_button.bind("<Enter>", on_enter)
        self.toggle_button.bind("<Leave>", on_leave)
        variable.trace_add("write", update_toggle)
        
        return frame
    
    def toggle_listening(self, *args):
        """Called when the listening toggle button is changed"""
        if self.listen_var.get():
            logger.info("Starting microphone listening")
            self.start_listening_callback()
        else:
            logger.info("Stopping microphone listening")
            self.stop_listening_callback()
    
    def process_queue(self):
        """Process incoming transcripts from the queue"""
        while self.processing:
            try:
                # Get the transcript from the queue
                transcript_data = self.topic_queue.get(timeout=0.1)
                
                # Extract source and text from the transcript
                source, text = self.parse_transcript(transcript_data)
                
                # Create a new topic and add it to the list
                if text:
                    self.add_topic(text, source)
                
                self.topic_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"Error processing transcript: {e}")
    
    def parse_transcript(self, transcript):
        """Parse the transcript to extract source and text"""
        try:
            # Extract source tag and text
            transcript = transcript.strip()
            if transcript.startswith('[ME]'):
                return 'ME', transcript[4:].strip()
            elif transcript.startswith('[OTHERS]'):
                return 'OTHERS', transcript[8:].strip()
            else:
                # Default to OTHERS if no source tag is found
                return 'OTHERS', transcript
        except Exception as e:
            logger.error(f"Error parsing transcript: {e}")
            return 'UNKNOWN', transcript
    
    def add_topic(self, text, source):
        """Add a new topic to the list"""
        topic = Topic(text=text, timestamp=datetime.now(), source=source)
        self.topics.append(topic)
        logger.info(f"Added new topic from {source}: {text[:50]}..." if len(text) > 50 else f"Added new topic: {text}")
    
    def add_transcript_to_queue(self, transcript):
        """Add a transcript to the queue for processing"""
        self.topic_queue.put(transcript)
    
    def update_ui(self):
        """Update the UI with the current topics"""
        # Save current scroll position
        yview = self.topic_listbox.yview()
        self.topic_listbox.delete(0, tk.END)
        
        # Refill with current topics
        for i, topic in enumerate(self.topics):
            self.topic_listbox.insert(tk.END, topic.get_display_text())
            if topic.selected:
                self.topic_listbox.itemconfig(i, {'bg': '#d0d0ff'})
                self.topic_listbox.selection_set(i)
        
        # Restore scroll position if needed
        if self.topic_listbox.size() > 0 and yview != (0.0, 1.0):
            try:
                self.topic_listbox.yview_moveto(yview[0])
            except:
                pass
        
        # Schedule the next update
        self.root.after(100, self.update_ui)
    
    def toggle_selection(self, event):
        """Toggle the selection state of a topic when clicked"""
        try:
            idx = self.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                # Toggle selection
                self.topics[idx].selected = not self.topics[idx].selected
                self.update_full_text_display(idx)
        except:
            pass
    
    def update_full_text_display(self, idx):
        """Update the full text display with the selected topic"""
        if 0 <= idx < len(self.topics):
            self.full_text.config(state="normal")
            self.full_text.delete(1.0, tk.END)
            self.full_text.insert(tk.END, self.topics[idx].text)
            self.full_text.config(state="disabled")
    
    def select_topics(self, select_all=True):
        """Select or deselect all topics"""
        for topic in self.topics:
            topic.selected = select_all
        
        if select_all:
            self.topic_listbox.selection_set(0, tk.END)
        else:
            self.topic_listbox.selection_clear(0, tk.END)
    
    def delete_topics(self, selected_only=True):
        """Delete selected topics or all topics"""
        if selected_only:
            self.topics = [topic for topic in self.topics if not topic.selected]
        else:
            self.topics = []
        self.topic_listbox.selection_clear(0, tk.END)
    
    def delete_topic(self, event):
        """Delete a single topic on right-click"""
        try:
            idx = self.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                del self.topics[idx]
                self.topic_listbox.selection_clear(0, tk.END)
        except:
            pass
    
    def show_full_topic(self, event):
        """Show the full text of the selected topic"""
        if event:
            try:
                selected_indices = self.topic_listbox.curselection()
                if selected_indices:
                    self.update_full_text_display(selected_indices[0])
            except:
                pass
    
    def submit_selected_topics(self, select_all_override=False): # Added optional override
        """Submit selected topics (or all if select_all_override is True) to the browser queue"""
        context = self.context_text.get(1.0, tk.END).strip()
        
        selected_topic_objects: List[Topic]
        if select_all_override:
            selected_topic_objects = list(self.topics) # Submit all topics
            if not selected_topic_objects:
                self.update_browser_status("warning", "Status: No topics available to submit all.")
                return
        else:
            selected_topic_objects = [topic for topic in self.topics if topic.selected]
            if not selected_topic_objects:
                self.update_browser_status("warning", "Status: No topics selected for submission.")
                return
        
        messages_for_submission = []
        if context:
            messages_for_submission.append(f"[CONTEXT] {context}")
        for topic_obj in selected_topic_objects:
            messages_for_submission.append(f"[{topic_obj.source}] {topic_obj.text}")
        
        combined_message_text = "\n".join(messages_for_submission)
        action_desc = "all" if select_all_override else str(len(selected_topic_objects))
        logger.info(f"UI: Preparing to submit {action_desc} topics.")
        
        self.submit_topics_callback(combined_message_text, selected_topic_objects) 
        
        self.update_browser_status("info", f"Status: Submitted {action_desc} topics for AI processing...")

    def submit_all_topics(self):
        """Selects all topics and then submits them."""
        logger.info("UI 'Submit All' button clicked.")
        # No need to actually call self.select_topics(True) visually if submit_selected_topics handles it
        self.submit_selected_topics(select_all_override=True)

    def clear_successfully_submitted_topics(self, successfully_submitted_topic_objects: List[Topic]):
        """Removes successfully submitted topics from the internal list and refreshes UI."""
        if not successfully_submitted_topic_objects:
            return

        # Create a set of IDs of the successfully submitted Topic objects for efficient removal
        # This assumes that the Topic objects passed back are the same instances
        # that are stored in self.topics.
        submitted_ids = {id(t) for t in successfully_submitted_topic_objects}

        # Filter out the submitted topics from the main list
        self.topics = [t for t in self.topics if id(t) not in submitted_ids]
        
        # Clear all selections in the listbox; update_ui will handle re-selection if any remain
        self.topic_listbox.selection_clear(0, tk.END)
        
        # The general self.update_ui() will refresh the listbox content.
        # No need to call it explicitly here if it's already running periodically.
        # However, for immediate feedback, you might: self.update_ui_now() if you make one.
        
        logger.info(f"Cleared {len(successfully_submitted_topic_objects)} successfully submitted topics from UI.")

    def on_closing(self):
        """Handle application closing"""
        logger.info("TopicsUI: on_closing called.")
        self.processing = False # Stop internal queue processing
        # self.stop_listening_callback() # This is good, AudioToChat will also call its stop
        if self.app_controller and hasattr(self.app_controller, 'on_closing_ui_initiated'):
            self.app_controller.on_closing_ui_initiated() # Let AudioToChat handle the full shutdown
        else: # Fallback if app_controller or method is missing
            self.stop_listening_callback()
            if self.root and self.root.winfo_exists():
                self.root.destroy()
