import os
import time
import re
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime
import queue
import glob
import shutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configuration
CONFIG = {
    "input_folder": r"C:\Users\kirill.levtov\Downloads\Special",
    "output_folder": r"C:\Users\kirill.levtov\Downloads\Output",
    "processed_folder": r"C:\Users\kirill.levtov\Downloads\Processed",  # New folder for processed files
    "file_pattern": "*.txt"
}

# Ensure folders exist
for folder in [CONFIG["output_folder"], CONFIG["processed_folder"]]:
    os.makedirs(folder, exist_ok=True)

class Topic:
    def __init__(self, text, timestamp):
        self.text = text
        self.timestamp = timestamp
        self.selected = False
    
    def get_display_text(self):
        time_str = self.timestamp.strftime("%H:%M")
        return f"[{time_str}] {self.text}"

class FileEventHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.txt'):
            self.callback(event.src_path)

class TopicProcessor:
    def __init__(self, root):
        self.root = root
        self.root.title("Topic Processor")
        self.root.geometry("900x600")
        self.topics = []
        self.topic_queue = queue.Queue()
        self.create_widgets()
        self.setup_file_watcher()
        
        # Process existing files in the folder
        self.process_existing_files()
        
        # Start the queue processing thread
        self.processing = True
        self.queue_thread = threading.Thread(target=self.process_queue)
        self.queue_thread.daemon = True
        self.queue_thread.start()
        
        # Update UI periodically
        self.root.after(100, self.update_ui)
    
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Top section - Topic List
        list_frame = ttk.LabelFrame(main_frame, text="Topics", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create a frame for buttons above the list
        button_frame = ttk.Frame(list_frame)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Select All button
        self.select_all_btn = ttk.Button(button_frame, text="Select All", command=self.select_all_topics)
        self.select_all_btn.pack(side=tk.LEFT, padx=5)
        
        # Deselect All button
        self.deselect_all_btn = ttk.Button(button_frame, text="Deselect All", command=self.deselect_all_topics)
        self.deselect_all_btn.pack(side=tk.LEFT, padx=5)
        
        # Delete Selection button
        self.delete_selection_btn = ttk.Button(button_frame, text="Delete Selection", command=self.delete_selected_topics)
        self.delete_selection_btn.pack(side=tk.LEFT, padx=5)
        
        # Delete All button
        self.delete_all_btn = ttk.Button(button_frame, text="Delete All", command=self.delete_all_topics)
        self.delete_all_btn.pack(side=tk.LEFT, padx=5)
        
        # Listen toggle
        self.listen_var = tk.BooleanVar(value=True)
        self.listen_toggle = self.create_toggle_switch(button_frame, "Listen", self.listen_var)
        self.listen_toggle.pack(side=tk.RIGHT, padx=5)
        
        # Topic listbox with scrollbar
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create scrollbar first
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Then create listbox and connect to scrollbar
        self.topic_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE, activestyle='none', 
                                        height=15, font=('TkDefaultFont', 10), 
                                        yscrollcommand=scrollbar.set)
        self.topic_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Connect scrollbar to listbox
        scrollbar.config(command=self.topic_listbox.yview)
        
        # First, bind ListboxSelect
        self.topic_listbox.bind("<<ListboxSelect>>", self.show_full_topic)
        # Then bind our click handler to ensure it runs last
        self.topic_listbox.bind("<ButtonRelease-1>", self.toggle_selection)
        self.topic_listbox.bind("<ButtonRelease-3>", self.delete_topic)
        
        # Bottom section - Full Topic Text
        text_frame = ttk.LabelFrame(main_frame, text="Full Topic Text", padding="5")
        text_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
        
        # Make full text area read-only
        self.full_text = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, height=3, state="disabled")
        self.full_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Context and Submit section
        context_frame = ttk.LabelFrame(main_frame, text="Context", padding="5")
        context_frame.pack(fill=tk.X, expand=False)
        
        self.context_text = scrolledtext.ScrolledText(context_frame, wrap=tk.WORD, height=2)
        self.context_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Submit button
        self.submit_btn = ttk.Button(main_frame, text="Submit Topics", command=self.submit_topics)
        self.submit_btn.pack(pady=10)
    
    def create_toggle_switch(self, parent, text, variable):
        """Create a custom toggle switch using labels instead of buttons"""
        frame = ttk.Frame(parent)
        
        # Create a label that will act as our toggle
        self.toggle_button = tk.Label(frame, 
                                    width=6, 
                                    text="ON",
                                    font=("TkDefaultFont", 9, "bold"),
                                    fg="white",  # Text color
                                    bg="#0b5394",  # Background color
                                    padx=2,
                                    pady=2,
                                    relief="raised",
                                    bd=1)
        self.toggle_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Label next to the toggle
        label = ttk.Label(frame, text=text)
        label.pack(side=tk.LEFT)
        
        # Function to update the button appearance
        def update_toggle(*args):
            if variable.get():
                self.toggle_button.config(text="ON", 
                                        bg="#0b5394",  # Dark blue
                                        fg="white")    # White text
            else:
                self.toggle_button.config(text="OFF", 
                                        bg="#666666",  # Dark gray
                                        fg="white")    # White text
        
        # Initial update
        update_toggle()
        
        # Connect the toggle button to the variable
        self.toggle_button.bind("<Button-1>", lambda e: [variable.set(not variable.get()), update_toggle()])
        
        # Also watch the variable for changes
        variable.trace_add("write", update_toggle)
        
        return frame
    
    def setup_file_watcher(self):
        self.observer = Observer()
        event_handler = FileEventHandler(self.queue_file)
        self.observer.schedule(event_handler, CONFIG["input_folder"], recursive=False)
        self.observer.start()
    
    def process_existing_files(self):
        for file_path in glob.glob(os.path.join(CONFIG["input_folder"], CONFIG["file_pattern"])):
            self.queue_file(file_path)
    
    def queue_file(self, file_path):
        self.topic_queue.put(file_path)
    
    def process_queue(self):
        while self.processing:
            try:
                file_path = self.topic_queue.get(timeout=1)
                if self.listen_var.get():  # Only process if listening
                    self.process_file(file_path)
                self.topic_queue.task_done()
            except queue.Empty:
                time.sleep(0.1)
    
    def process_file(self, file_path):
        retry_count = 0
        max_retries = 3
        retry_delay = 0.5  # seconds
        
        while retry_count < max_retries:
            try:
                # Get file creation time
                timestamp = datetime.fromtimestamp(os.path.getctime(file_path))
                
                # Read file content
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        content = file.read()
                except UnicodeDecodeError:
                    # Try with a different encoding if UTF-8 fails
                    with open(file_path, 'r', encoding='cp1252') as file:
                        content = file.read()
                
                # Process the file to extract the last chatbot response
                last_response = self.extract_last_response(content)
                if last_response:
                    # Break into topics (each line is a topic)
                    topics = [line.strip() for line in last_response.split('\n') if line.strip()]
                    
                    # Add to our topics list
                    for topic_text in topics:
                        self.topics.append(Topic(topic_text, timestamp))
                
                # Move the file to processed folder instead of deleting it
                try:
                    # Create a unique filename for the moved file
                    basename = os.path.basename(file_path)
                    dest_path = os.path.join(CONFIG["processed_folder"], basename)
                    
                    # If the file already exists in the processed folder, add a timestamp
                    if os.path.exists(dest_path):
                        name, ext = os.path.splitext(basename)
                        timestamp_str = datetime.now().strftime("%H%M%S")
                        dest_path = os.path.join(CONFIG["processed_folder"], f"{name}_{timestamp_str}{ext}")
                    
                    # Move the file
                    shutil.move(file_path, dest_path)
                    # If we get here, the operation was successful
                    break
                except Exception as e:
                    print(f"Error moving file {file_path}: {e}")
                    # If move fails, we'll retry
                    retry_count += 1
                    time.sleep(retry_delay)
                    continue
                    
            except PermissionError as e:
                print(f"Permission error processing file {file_path}: {e}. Retry {retry_count+1}/{max_retries}")
                retry_count += 1
                time.sleep(retry_delay)
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                break  # For non-permission errors, don't retry
    
    def extract_last_response(self, content):
        """
        Extract the last AI response from a chat transcript file.
        
        This function focuses on extracting the complete text content of the last AI response,
        ensuring no parts of the response are accidentally truncated.
        
        Args:
            content (str): The content of the chat transcript file
            
        Returns:
            str: The complete extracted last response text, or None if no response is found
        """
        # First, try to find the last user prompt section
        user_prompt_matches = re.findall(r"User prompt \d+ of \d+ - [^:]+:(.*?)(?=\n\nUser prompt|\Z)", content, re.DOTALL)
        
        if not user_prompt_matches:
            return None
            
        # Get the section that contains the last user prompt and its response
        last_section = user_prompt_matches[-1].strip()
        
        # Split the section by double newlines to separate prompt from response
        parts = last_section.split("\n\n")
        if len(parts) < 2:
            return None
        
        # The first part is the user prompt, everything after should be the response
        # But we need to check if the model name is on its own line
        remaining_parts = parts[1:]
        
        # Join all parts after the user prompt
        potential_response = "\n\n".join(remaining_parts)
        
        # Now extract just the model response by removing the model identifier
        model_line_match = re.match(r"([A-Za-z][A-Za-z0-9\s\.-]+):(.*)", potential_response, re.DOTALL)
        
        if model_line_match:
            # Return the complete response
            return model_line_match.group(2).strip()
        
        # If we can't find a clear model identifier, return all content after the prompt
        # This is a fallback case
        return potential_response.strip()

    def update_ui(self):
        # Update the topic list without changing scroll position
        yview = self.topic_listbox.yview()
                
        # Clear and refill the listbox
        self.topic_listbox.delete(0, tk.END)
        
        # Refill with current topics
        for i, topic in enumerate(self.topics):
            self.topic_listbox.insert(tk.END, topic.get_display_text())
            # Use the same highlight color for both manual and Select All selections
            if topic.selected:
                self.topic_listbox.itemconfig(i, {'bg': '#d0d0ff'})
                # Also update the listbox selection to match our internal selection state
                self.topic_listbox.selection_set(i)
        
        # Restore scroll position if needed
        if self.topic_listbox.size() > 0 and yview != (0.0, 1.0):
            try:
                self.topic_listbox.yview_moveto(yview[0])
            except:
                pass  # Ignore errors if the view can't be restored
        
        # Schedule the next update
        self.root.after(100, self.update_ui)
    
    def toggle_selection(self, event):
        # Get clicked item index
        try:
            idx = self.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                # Toggle selection
                self.topics[idx].selected = not self.topics[idx].selected
                
                # Always update the full text display with the clicked topic text
                self.full_text.config(state="normal")
                self.full_text.delete(1.0, tk.END)
                self.full_text.insert(tk.END, self.topics[idx].text)
                self.full_text.config(state="disabled")
                
                # Clear listbox selection to avoid confusion
                self.topic_listbox.selection_clear(0, tk.END)
                # Update the listbox selection to match our internal selection state
                for i, topic in enumerate(self.topics):
                    if topic.selected:
                        self.topic_listbox.selection_set(i)
        except:
            pass  # Ignore errors if the item can't be selected
    
    def update_full_text_display(self, idx):
        if 0 <= idx < len(self.topics):
            # Enable, clear, insert, then disable
            self.full_text.config(state="normal")
            self.full_text.delete(1.0, tk.END)
            self.full_text.insert(tk.END, self.topics[idx].text)
            self.full_text.config(state="disabled")

    def select_all_topics(self):
        for topic in self.topics:
            topic.selected = True
        # Update the listbox selection to match our internal selection state
        for i in range(len(self.topics)):
            self.topic_listbox.selection_set(i)
    
    def deselect_all_topics(self):
        for topic in self.topics:
            topic.selected = False
        # Clear the listbox selection to match our internal selection state
        self.topic_listbox.selection_clear(0, tk.END)
    
    def delete_topic(self, event):
        # Get clicked item index
        try:
            idx = self.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                del self.topics[idx]
                # Clear listbox selection after deletion
                self.topic_listbox.selection_clear(0, tk.END)
        except:
            pass  # Ignore errors if the item can't be deleted
    
    def delete_all_topics(self):
        self.topics = []
        # Clear listbox selection
        self.topic_listbox.selection_clear(0, tk.END)
    
    def delete_selected_topics(self):
        # Remove all selected topics
        self.topics = [topic for topic in self.topics if not topic.selected]
        # Clear listbox selection after deletion
        self.topic_listbox.selection_clear(0, tk.END)
    
    def show_full_topic(self, event):
        # Only update if the event is not None (meaning it was triggered by the system)
        if event:
            try:
                selected_indices = self.topic_listbox.curselection()
                if selected_indices and len(selected_indices) > 0:
                    idx = selected_indices[0]
                    if 0 <= idx < len(self.topics):
                        # Enable, clear, insert, then disable
                        self.full_text.config(state="normal")
                        self.full_text.delete(1.0, tk.END)
                        self.full_text.insert(tk.END, self.topics[idx].text)
                        self.full_text.config(state="disabled")
            except:
                pass  # Ignore errors if the topic can't be shown
    
    def submit_topics(self):
        # Get context text
        context = self.context_text.get(1.0, tk.END).strip()
        
        # Get selected topics
        selected_topics = [topic for topic in self.topics if topic.selected]
        
        if selected_topics:
            # Create output filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(CONFIG["output_folder"], f"topics_{timestamp}.txt")
            
            # Write to output file
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    # Write context if provided
                    if context:
                        f.write(f"CONTEXT:\n{context}\n\n")
                    
                    # Write topics
                    f.write("TOPICS:\n")
                    for i, topic in enumerate(selected_topics):
                        time_str = topic.timestamp.strftime("%H:%M")
                        f.write(f"{i+1}. [{time_str}] {topic.text}\n")
                
                # Remove selected topics from the list
                self.topics = [topic for topic in self.topics if not topic.selected]
                
                # Clear context
                self.context_text.delete(1.0, tk.END)
                
                # Clear listbox selection after submission
                self.topic_listbox.selection_clear(0, tk.END)
            except Exception as e:
                print(f"Error writing to output file: {e}")
    
    def on_closing(self):
        self.processing = False
        self.observer.stop()
        self.observer.join()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = TopicProcessor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()