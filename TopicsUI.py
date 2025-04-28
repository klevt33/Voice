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
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configuration
CONFIG = {
    "input_folder": r"C:\Users\kirill.levtov\Downloads\Special",
    "output_folder": r"C:\Users\kirill.levtov\Downloads\Output",
    "processed_folder": r"C:\Users\kirill.levtov\Downloads\Processed",
    "file_pattern": "*.txt"
}

# Ensure folders exist
for folder in [CONFIG["output_folder"], CONFIG["processed_folder"]]:
    os.makedirs(folder, exist_ok=True)

@dataclass
class Topic:
    text: str
    timestamp: datetime
    selected: bool = False
    
    def get_display_text(self):
        return f"[{self.timestamp.strftime('%H:%M')}] {self.text}"

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
        self.queue_thread = threading.Thread(target=self.process_queue, daemon=True)
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
        
        # Buttons
        ttk.Button(button_frame, text="Select All", command=lambda: self.select_topics(True)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Deselect All", command=lambda: self.select_topics(False)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete Selection", command=lambda: self.delete_topics(selected_only=True)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete All", command=lambda: self.delete_topics(selected_only=False)).pack(side=tk.LEFT, padx=5)
        
        # Listen toggle
        self.listen_var = tk.BooleanVar(value=True)
        self.create_toggle_switch(button_frame, "Listen", self.listen_var).pack(side=tk.RIGHT, padx=5)
        
        # Topic listbox with scrollbar
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
        
        # Bottom section - Full Topic Text
        text_frame = ttk.LabelFrame(main_frame, text="Full Topic Text", padding="5")
        text_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
        
        self.full_text = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, height=3, state="disabled")
        self.full_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Context and Submit section
        context_frame = ttk.LabelFrame(main_frame, text="Context", padding="5")
        context_frame.pack(fill=tk.X, expand=False)
        
        self.context_text = scrolledtext.ScrolledText(context_frame, wrap=tk.WORD, height=2)
        self.context_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Submit button
        ttk.Button(main_frame, text="Submit Topics", command=self.submit_topics).pack(pady=10)
    
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
    
    def setup_file_watcher(self):
        self.observer = Observer()
        self.observer.schedule(
            FileEventHandler(self.topic_queue.put), 
            CONFIG["input_folder"], 
            recursive=False
        )
        self.observer.start()
    
    def process_existing_files(self):
        for file_path in glob.glob(os.path.join(CONFIG["input_folder"], CONFIG["file_pattern"])):
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
        for attempt in range(3):  # Max 3 retries
            try:
                # Get file creation time
                timestamp = datetime.fromtimestamp(os.path.getctime(file_path))
                
                # Read file content with fallback encoding
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        content = file.read()
                except UnicodeDecodeError:
                    with open(file_path, 'r', encoding='cp1252') as file:
                        content = file.read()
                
                # Process the file to extract the last chatbot response
                last_response = self.extract_last_response(content)
                if last_response:
                    # Add each line as a topic
                    for topic_text in [line.strip() for line in last_response.split('\n') if line.strip()]:
                        self.topics.append(Topic(topic_text, timestamp))
                
                # Move the file to processed folder
                basename = os.path.basename(file_path)
                dest_path = os.path.join(CONFIG["processed_folder"], basename)
                
                # Add timestamp if file exists
                if os.path.exists(dest_path):
                    name, ext = os.path.splitext(basename)
                    timestamp_str = datetime.now().strftime("%H%M%S")
                    dest_path = os.path.join(CONFIG["processed_folder"], f"{name}_{timestamp_str}{ext}")
                
                shutil.move(file_path, dest_path)
                return  # Success, exit the retry loop
                
            except PermissionError:
                if attempt < 2:  # Don't sleep on the last attempt
                    time.sleep(0.5 * (attempt + 1))  # Increasing delay
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                return  # Don't retry on non-permission errors
    
    def extract_last_response(self, content):
        # Find the last user prompt section
        user_prompt_matches = re.findall(r"User prompt \d+ of \d+ - [^:]+:(.*?)(?=\n\nUser prompt|\Z)", content, re.DOTALL)
        
        if not user_prompt_matches:
            return None
            
        # Get the last section and split it to separate prompt from response
        last_section = user_prompt_matches[-1].strip()
        parts = last_section.split("\n\n")
        if len(parts) < 2:
            return None
        
        # Everything after the first part should be the response
        potential_response = "\n\n".join(parts[1:])
        
        # Extract just the model response by removing the model identifier
        model_line_match = re.match(r"([A-Za-z][A-Za-z0-9\s\.-]+):(.*)", potential_response, re.DOTALL)
        
        return model_line_match.group(2).strip() if model_line_match else potential_response.strip()

    def update_ui(self):
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
        try:
            idx = self.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                # Toggle selection
                self.topics[idx].selected = not self.topics[idx].selected
                self.update_full_text_display(idx)
        except:
            pass
    
    def update_full_text_display(self, idx):
        if 0 <= idx < len(self.topics):
            self.full_text.config(state="normal")
            self.full_text.delete(1.0, tk.END)
            self.full_text.insert(tk.END, self.topics[idx].text)
            self.full_text.config(state="disabled")
    
    def select_topics(self, select_all=True):
        for topic in self.topics:
            topic.selected = select_all
        
        if select_all:
            self.topic_listbox.selection_set(0, tk.END)
        else:
            self.topic_listbox.selection_clear(0, tk.END)
    
    def delete_topics(self, selected_only=True):
        if selected_only:
            self.topics = [topic for topic in self.topics if not topic.selected]
        else:
            self.topics = []
        self.topic_listbox.selection_clear(0, tk.END)
    
    def delete_topic(self, event):
        try:
            idx = self.topic_listbox.nearest(event.y)
            if 0 <= idx < len(self.topics):
                del self.topics[idx]
                self.topic_listbox.selection_clear(0, tk.END)
        except:
            pass
    
    def show_full_topic(self, event):
        if event:
            try:
                selected_indices = self.topic_listbox.curselection()
                if selected_indices:
                    self.update_full_text_display(selected_indices[0])
            except:
                pass
    
    def submit_topics(self):
        context = self.context_text.get(1.0, tk.END).strip()
        selected_topics = [topic for topic in self.topics if topic.selected]
        
        if selected_topics:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(CONFIG["output_folder"], f"topics_{timestamp}.txt")
            
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    if context:
                        f.write(f"CONTEXT:\n{context}\n\n")
                    
                    f.write("TOPICS:\n")
                    for i, topic in enumerate(selected_topics):
                        f.write(f"{i+1}. [{topic.timestamp.strftime('%H:%M')}] {topic.text}\n")
                
                # Clean up after successful submission
                self.topics = [topic for topic in self.topics if not topic.selected]
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