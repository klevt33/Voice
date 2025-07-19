# Application Architecture: Audio Transcription Processor

## 1. Overview

This document details the software architecture of the Audio Transcription Processor application. The primary goal of this application is to capture audio from two distinct sources in real-time, transcribe the spoken content, and facilitate its submission to AI chat websites like ChatGPT or Perplexity.

The application is designed to be a "sidekick" during conversations, meetings, or interviews. It listens to both the user ("ME") and other participants ("OTHERS"), separates their speech into distinct topics, and allows the user to manage and submit these topics for summarization, analysis, or further discussion with an AI.

**Core Features:**
- **Dual Audio Source Capture:** Simultaneously records from a user's microphone and a system loopback audio device.
- **Real-time Transcription:** Uses the `faster-whisper` library for efficient, high-quality speech-to-text conversion.
- **Topic Management UI:** A `tkinter`-based GUI allows the user to view, select, and manage transcribed text segments (topics). Includes both copy-to-clipboard and submit-to-AI functionality.
- **Browser Automation:** Integrates with a running instance of Google Chrome (in debug mode) using `selenium` to automate the submission of topics to AI chat websites.
- **Auto-Submit Functionality:** Provides modes to automatically send transcriptions to the AI chat based on their source (e.g., automatically submit everything said by "OTHERS").

---

## 2. Architectural Design

The application employs a **centralized orchestrator pattern** with a strong emphasis on **separation of concerns**. The architecture is designed to be modular and multi-threaded to handle concurrent tasks (audio I/O, transcription, UI management, browser communication) without blocking.

### 2.1. Core Components

The system is broken down into several key components, each with a distinct responsibility:

![Architecture Diagram](https://i.imgur.com/your-diagram-image.png)  *(Self-correction: A diagram would be ideal here, but as a text-based model, I will describe the relationships in detail below.)*

- **`AudioToChat` (Orchestrator):** The main class that initializes and connects all other components. It owns the main application loop and manages the graceful startup and shutdown of the entire system.
- **`StateManager` (State):** A simple class that holds the shared state of the application, such as whether the threads should be active (`run_threads_ref`) or if the microphones are currently listening. This prevents state from being scattered across different modules.
- **`ServiceManager` (Services):** Manages the lifecycle of long-running external services, specifically `PyAudio` for audio capture and the `BrowserManager` for Selenium automation. It is responsible for initializing, starting, and stopping these services and their associated threads.
- **`UIController` & `UIView` (UI Layer):** Follows a Model-View-Controller (MVC) pattern.
    - `UIController` (`TopicsUI.py`): Contains all the application logic for the user interface. It handles button clicks, manages the list of topics, and communicates with the main orchestrator (`AudioToChat`).
    - `UIView` (`ui_view.py`): Contains all the `tkinter` widget definitions and layout. It is purely responsible for the visual presentation and has no application logic.
- **`TopicRouter` (Routing):** A dedicated class responsible for deciding the destination of a newly transcribed topic. Based on the current `auto_submit_mode`, it routes the topic to either the `UIController` for display or the `BrowserManager` for immediate submission.
- **`BrowserManager` & `ChatPage` (Browser Layer):**
    - `BrowserManager` (`browser.py`): A high-level controller for browser interactions. It manages the communication thread and the submission queue (`browser_queue`). It delegates all page-specific actions to the `ChatPage` object.
    - `ChatPage` (`chat_page.py`): A low-level class that encapsulates all direct `selenium` interactions with a specific chat website. It knows how to find the input box, click buttons, and submit text for a given site, abstracting these details away from the rest of the application.
- **`config.py` (Configuration):** A centralized file for all user-configurable settings, such as microphone indices, Whisper model settings, and CSS selectors for different AI chat websites.

---

## 3. Data Flow and Threading Model

The application is heavily multi-threaded to ensure the UI remains responsive while background tasks are running. Communication between threads is handled safely using `queue.Queue`.

### 3.1. Threading Model

1.  **Main Thread:** Runs the `tkinter` UI event loop (`root.mainloop()`). This is the only thread that should directly interact with UI widgets.
2.  **Audio Recording Threads (x2):** One thread for each audio source ("ME" and "OTHERS"). These threads, defined in `audio_handler.py`, continuously listen to a microphone and put chunks of recorded audio into the `audio_queue`.
3.  **Transcription Thread:** A single thread that consumes audio chunks from the `audio_queue`, transcribes them using `faster-whisper`, and places the resulting `Topic` object into the `transcribed_topics_queue`.
4.  **Topic Processing Thread:** Managed by `AudioToChat`, this thread consumes `Topic` objects from the `transcribed_topics_queue` and passes them to the `TopicRouter`.
5.  **Browser Communication Thread:** Managed by `BrowserManager`, this thread consumes submission requests from the `browser_queue` and executes them using Selenium.
6.  **UI Topic Queue Thread:** Managed by `UIController`, this thread consumes topics routed to the UI and adds them to the topic list for display.

### 3.2. Queue-Based Data Flow

The flow of data is orchestrated through a series of queues:

1.  **`audio_queue`**:
    - **Producers:** The two `recording_thread` instances.
    - **Consumer:** The `transcription_thread`.
    - **Content:** `AudioSegment` objects containing raw audio data.

2.  **`transcribed_topics_queue`**:
    - **Producer:** The `transcription_thread`.
    - **Consumer:** The `topic_processing_loop` in `AudioToChat`.
    - **Content:** `Topic` objects containing the transcribed text and metadata.

3.  **Routing Decision (by `TopicRouter`)**: The `TopicRouter` inspects each `Topic` and, based on the `auto_submit_mode`, puts it into one of two queues:

    a. **`UIController.topic_queue`**:
        - **Producer:** The `TopicRouter`.
        - **Consumer:** The `UIController`'s internal `process_topic_queue` thread.
        - **Purpose:** To add topics to the main UI list for manual review.

    b. **`BrowserManager.browser_queue`**:
        - **Producers:**
            - The `TopicRouter` (for auto-submissions).
            - The `UIController` (when the user manually clicks "Submit Selected" or "Submit All").
        - **Consumer:** The `_browser_communication_loop` in `BrowserManager`.
        - **Purpose:** To send content to the AI chat website.

This decoupled, queue-based system ensures that each component can operate asynchronously without direct dependencies on the others, improving stability and performance.

---

## 4. Key Workflows

### 4.1. Application Startup
1.  `AudioToChat` is instantiated. It creates the `StateManager`, `UIController`, `ServiceManager`, and `TopicRouter`.
2.  The `run()` method is called.
3.  `ServiceManager` initializes PyAudio and then the `BrowserManager`.
4.  `BrowserManager` connects to Chrome and creates a `ChatPage` instance.
5.  `ServiceManager` starts all background threads: two audio recorders and one transcriber.
6.  `AudioToChat` starts its `topic_processing_loop` to watch the `transcribed_topics_queue`.
7.  The `tkinter` `root.mainloop()` is started, and the UI becomes visible and interactive.

### 4.2. Copy to Clipboard Workflow
This workflow allows users to copy topics for use in external applications without removing them from the UI.
1.  User clicks "Copy Selected" or "Copy All" button in the UI.
2.  `UIController` consolidates the selected/all topics with context (if present) into a formatted string.
3.  The consolidated text is copied to the system clipboard using `pyperclip`.
4.  Topics remain in the UI list (unlike submission which removes successfully submitted topics).
5.  User receives status feedback confirming the copy operation.

### 4.3. Browser Submission ("Prime and Submit")
This is a critical workflow to handle websites where the submit button is disabled until text is entered.
1.  A submission item is placed in the `browser_queue`.
2.  The `_browser_communication_loop` wakes up and gets the item.
3.  It calls `chat_page.prime_input()`, which enters "Waiting..." into the text area. This is intended to trigger the website's JavaScript to enable the submit button.
4.  The loop then polls `chat_page.is_ready_for_input()`, repeatedly checking if the submit button has become clickable.
5.  **Crucially**, only after `is_ready_for_input()` returns `SUCCESS` does the loop drain any additional items that have arrived in the `browser_queue`, maximizing the batch size.
6.  The final, combined payload is constructed and sent to `chat_page.submit_message()`.
7.  A callback is sent to the UI to update its status.

---

## 5. Setup and Configuration

### 5.1. Dependencies
All required Python packages are listed in `requirements.txt`.

### 5.2. `config.py`
This file is the central point for configuration:
- **`MIC_INDEX_ME`, `MIC_INDEX_OTHERS`**: The numeric indices of the two audio devices. These must be set correctly by the user (the `scan_mics.py` utility can help).
- **Whisper Settings**: `WHISPER_MODEL`, `COMPUTE_TYPE`, etc., control the performance and accuracy of the transcription.
- **`CHATS` Dictionary**: This is the core of the browser automation configuration. Each entry represents a website and contains:
    - `url`: The base URL for the chat.
    - `prompt_..._file`: Paths to text files containing initial system prompts.
    - `..._selector`: **CSS selectors** used by Selenium to find key elements on the page (input box, submit button, etc.). These are critical for the automation to work and are the most likely part to require updates if a website's design changes.

### 5.3. Browser Requirement
The application **requires** a running instance of Google Chrome to be launched with a remote debugging port. This allows Selenium to connect to an existing browser session without launching a new one.

Example command to launch Chrome:
```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

---

## 6. How to Continue Development

A new developer should focus on the following areas for common tasks:

- **Adding a New Chat Website:**
    1.  Add a new entry to the `CHATS` dictionary in `config.py`.
    2.  Use the browser's developer tools to find stable CSS selectors for the new site's input field, submit button, and new thread button.
    3.  Add these selectors to the new dictionary entry.
    4.  Create new prompt files if desired.
    5.  The existing `ChatPage` class should work without modification if the new site follows a similar structure.

- **Modifying UI Behavior:**
    1.  Logic changes (e.g., how topics are combined) should be made in `UIController` (`TopicsUI.py`).
    2.  Visual changes (e.g., adding a new button, changing layout) should be made in `UIView` (`ui_view.py`).

- **Changing Transcription Logic:**
    1.  All transcription logic is contained within the `transcription_thread` function in `transcription.py`.

- **Debugging Browser Issues:**
    1.  The most common failure point is a changed CSS selector. Start by verifying the selectors in `config.py` against the live website.
    2.  Add `time.sleep()` calls and logging statements within the methods of `chat_page.py` to observe the automation step-by-step.
