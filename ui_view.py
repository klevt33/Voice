# ui_view.py
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Optional

class UIView(ttk.Frame):
    """
    Manages the creation and layout of all UI widgets.
    This class is responsible for the "View" part of the UI.
    """
    def __init__(self, parent, controller):
        super().__init__(parent, padding="10")
        self.pack(fill=tk.BOTH, expand=True)

        self.controller = controller

        self.create_widgets()

    def create_widgets(self):
        # Configure grid layout
        self.grid_rowconfigure(0, weight=1)  # Topics area
        self.grid_rowconfigure(1, weight=0)  # Full Topic Text
        self.grid_rowconfigure(2, weight=0)  # Context
        self.grid_rowconfigure(3, weight=0)  # Buttons
        self.grid_rowconfigure(4, weight=0)  # Status
        self.grid_columnconfigure(0, weight=1)

        # --- Main Frames using Grid ---
        self.list_frame = ttk.LabelFrame(self, text="Topics", padding="5")
        self.list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))

        # Store references to frames for toggle functionality
        self.text_frame = ttk.LabelFrame(self, text="Full Topic Text", padding="5")
        self.text_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))

        self.context_frame = ttk.LabelFrame(self, text="Context", padding="5")
        self.context_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 5))

        self.buttons_main_frame = ttk.Frame(self)
        self.buttons_main_frame.grid(row=3, column=0, pady=5)

        status_bar_frame = ttk.Frame(self, relief=tk.SUNKEN, padding="2 2 2 2")
        status_bar_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=(5, 10))

        # --- List Frame Widgets ---
        self._create_list_frame_widgets(self.list_frame)

        # --- Full Text Widget ---
        self.full_text = scrolledtext.ScrolledText(self.text_frame, wrap=tk.WORD, height=3, state="disabled")
        self.full_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # --- Context Toggle (positioned at title level) ---
        self._create_context_toggle_title_level()

        # --- Context Widget ---
        self.context_text = scrolledtext.ScrolledText(self.context_frame, wrap=tk.WORD, height=2)
        self.context_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Copy and Submit Buttons ---
        self._create_action_buttons(self.buttons_main_frame)

        # --- Status Bar ---
        self._create_status_bar(status_bar_frame)

    def _create_list_frame_widgets(self, parent):
        top_button_area_frame = ttk.Frame(parent)
        top_button_area_frame.pack(fill=tk.X, padx=5, pady=5)

        # Left Buttons
        left_buttons_frame = ttk.Frame(top_button_area_frame)
        left_buttons_frame.pack(side=tk.LEFT, anchor=tk.W)
        ttk.Button(left_buttons_frame, text="Select All", command=lambda: self.controller.select_topics(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons_frame, text="Deselect All", command=lambda: self.controller.select_topics(False)).pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons_frame, text="Delete Selection", command=lambda: self.controller.delete_topics(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(left_buttons_frame, text="Delete All", command=lambda: self.controller.delete_topics(False)).pack(side=tk.LEFT, padx=2)

        # Right Buttons
        right_buttons_frame = ttk.Frame(top_button_area_frame)
        right_buttons_frame.pack(side=tk.RIGHT, anchor=tk.E)
        self._create_right_buttons(right_buttons_frame)

        # Listbox
        list_container = ttk.Frame(parent)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.topic_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE, activestyle='none', 
                                        height=15, font=('TkDefaultFont', 10), 
                                        yscrollcommand=scrollbar.set)
        self.topic_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.topic_listbox.yview)
        self.topic_listbox.bind("<<ListboxSelect>>", self.controller.show_full_topic)
        self.topic_listbox.bind("<ButtonRelease-1>", self.controller.toggle_selection)
        self.topic_listbox.bind("<ButtonRelease-3>", self.controller.delete_topic)

    def _create_right_buttons(self, parent):
        # Auto-Submit Dropdown
        auto_submit_frame = ttk.Frame(parent)
        auto_submit_frame.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(auto_submit_frame, text="Auto-Submit:").pack(side=tk.LEFT)
        self.auto_submit_var = tk.StringVar(value="Off")
        self.auto_submit_options = ["Off", "Others", "All"]
        auto_submit_menu = ttk.OptionMenu(
            auto_submit_frame,
            self.auto_submit_var,
            self.auto_submit_options[0],
            *self.auto_submit_options,
            command=self.controller.on_auto_submit_change
        )
        auto_submit_menu.pack(side=tk.LEFT)

        # New Thread Button
        ttk.Button(parent, text="New Thread", command=self.controller.request_new_ai_thread_ui).pack(side=tk.LEFT, padx=(0, 5))

        # Listen Toggle
        self.listen_var = tk.BooleanVar(value=False)
        self.listen_var.trace_add("write", self.controller.toggle_listening)
        self.create_toggle_switch(parent, "Listen", self.listen_var).pack(side=tk.LEFT, padx=5)

    def _create_status_bar(self, parent):
        self.status_colors = {
            "default": ("gray", "Status: Initializing..."),
            "browser_ready": ("green", "AI Ready"),
            "browser_input_unavailable": ("#FF8C00", "AI Input Unavailable"), 
            "browser_human_verification": ("red", "AI Human Verification!"),
            "info": ("blue", "Info"),
            "success": ("green", "Success"),
            "warning": ("#FF8C00", "Warning"), 
            "error": ("red", "Error")
        }
        self.browser_status_indicator_label = ttk.Label(parent, text="●", font=("TkDefaultFont", 12, "bold"))
        self.browser_status_indicator_label.pack(side=tk.LEFT, padx=(5, 2))
        self.status_message_label = ttk.Label(parent, text="")
        self.status_message_label.pack(side=tk.LEFT, padx=(2, 5), fill=tk.X, expand=True)
        self.update_browser_status("default")

    def create_toggle_switch(self, parent, text, variable):
        frame = ttk.Frame(parent)
        toggle_button = tk.Label(frame, width=6, text="OFF", font=("TkDefaultFont", 9, "bold"),
                                 fg="white", bg="#666666", padx=2, pady=2, relief="raised", bd=1)
        toggle_button.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(frame, text=text).pack(side=tk.LEFT)

        def update_toggle(*args):
            state = variable.get()
            toggle_button.config(text="ON" if state else "OFF", bg="#0b5394" if state else "#666666")

        toggle_button.bind("<Button-1>", lambda e: variable.set(not variable.get()))
        variable.trace_add("write", update_toggle)
        return frame

    def _create_context_toggle_title_level(self):
        """Create context toggle positioned at the title level of the text frame"""
        self.show_context_var = tk.BooleanVar(value=True)
        self.show_context_var.trace_add("write", self._toggle_context_visibility)
        
        context_checkbox = ttk.Checkbutton(
            self.text_frame, 
            text="Show Context", 
            variable=self.show_context_var
        )
        context_checkbox.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=-24)

    def _toggle_context_visibility(self, *args):
        """Toggle between showing/hiding context field and adjusting full text height"""
        show_context = self.show_context_var.get()
        
        if show_context:
            # Mode 1: Show context field
            self.context_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 5))
            # Topics area gets weight, Full Topic Text stays minimal
            self.grid_rowconfigure(0, weight=1)  # Topics - expandable
            self.grid_rowconfigure(1, weight=0)  # Full Topic Text - fixed height
            self.full_text.config(height=3)
        else:
            # Mode 2: Hide context, give most space to Full Topic Text
            self.context_frame.grid_remove()
            # Give Topics minimal weight, Full Topic Text gets most weight
            self.grid_rowconfigure(0, weight=1)  # Topics - minimal expansion to maintain size
            self.grid_rowconfigure(1, weight=10)  # Full Topic Text - gets most of the extra space
            self.full_text.config(height=8)  # Larger height to use the extra space

    def _create_action_buttons(self, parent):
        # Copy buttons (left side)
        ttk.Button(parent, text="Copy Selected", command=self.controller.copy_selected_topics).pack(side=tk.LEFT, padx=5)
        ttk.Button(parent, text="Copy All", command=self.controller.copy_all_topics).pack(side=tk.LEFT, padx=(0, 20))
        
        # Submit buttons (right side)
        ttk.Button(parent, text="Submit Selected", command=self.controller.submit_selected_topics).pack(side=tk.LEFT, padx=(20, 5))
        ttk.Button(parent, text="Submit All", command=self.controller.submit_all_topics).pack(side=tk.LEFT, padx=5)

    def update_browser_status(self, status_key: str, custom_message: Optional[str] = None):
        color, default_message = self.status_colors.get(status_key, ("gray", "Status: Unknown"))
        message_to_display = custom_message if custom_message is not None else default_message
        self.browser_status_indicator_label.config(foreground=color)
        self.status_message_label.config(text=message_to_display, foreground=color)
