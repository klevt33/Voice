# Audio Transcription Processor

## 1. Project Overview

The Audio Transcription Processor is a real-time assistance tool designed to empower users in technical discussions. It captures audio from two separate microphone sources ([ME] for the user, [OTHERS] for conversation partners), transcribes the speech to text in real-time, and displays the snippets in a user-friendly interface.

The user can then select relevant snippets, add supplementary text context, and submit the compiled information to an AI chat service (like Perplexity or ChatGPT) for analysis, summarization, or to generate technical insights. The entire workflow is designed to be seamless, providing a "digital expert" that listens to the conversation and provides actionable intelligence on demand.

## 2. Core Features

-   **Dual-Microphone Real-Time Transcription:** Captures and transcribes audio simultaneously from two distinct sources, labeling them `[ME]` and `[OTHERS]`.
-   **GPU-Accelerated Transcription:** Leverages `faster-whisper` and an NVIDIA GPU (via CUDA) for high-speed, accurate speech-to-text processing.
-   **Interactive Tkinter UI:**
    -   Displays transcribed snippets in a chronological list.
    -   Allows for multi-selection, select/deselect all, and deletion of topics.
    -   Provides a text field for adding custom context to submissions.
    -   Features controls to start/stop listening and to manage the AI chat session.
-   **Auto-Submit Mode:**
    -   **Off:** Default manual mode.
    -   **Others:** Automatically sends transcriptions from the `[OTHERS]` source to the AI.
    -   **All:** Automatically sends all transcriptions to the AI.
-   **Seamless Browser Automation:**
    -   Integrates with a running instance of Google Chrome using Selenium via a remote debugging port.
    -   Navigates and interacts with AI chat websites automatically.
-   **Multi-AI Chat Support:**
    -   Easily configurable to work with different AI chat services (e.g., Perplexity, ChatGPT).
    -   Configuration is centralized in `config.py`, allowing for different URLs, CSS selectors, and input methods (`clipboard` paste vs. `send_keys`).
-   **Advanced Prompting System:**
    -   Uses an `prompt_init.txt` for a one-time system initialization prompt at the start of a session.
    -   Uses a `prompt_msg.txt` to prepend a task-specific directive to every subsequent submission of topics.
-   **Robust Session Management:**
    -   Intelligently detects if the browser is already on the target AI chat site.
    -   Provides a "New Thread" button in the UI to start a fresh conversation at any time, optionally sending along context from the UI.
-   **Error Handling:** Includes logic to detect when an AI chat page might be waiting for human verification and preserves user input if a submission fails.

## 3. Architecture & Technology Stack

The application uses a modular, multi-threaded architecture designed for responsiveness and separation of concerns. A central orchestrator manages the lifecycle of various components, which communicate asynchronously using thread-safe queues.

-   **Backend Language:** Python
-   **UI Framework:** Tkinter
-   **Audio Capture:** PyAudio
-   **Real-Time Transcription:** `faster-whisper` (built on `CTranslate2`)
-   **Browser Automation:** `selenium`
-   **Key Libraries:**
    -   `pip-tools`: For generating reproducible `requirements.txt` files.
    -   `torch`: For GPU acceleration.
    -   `pyperclip`: For reliable text pasting into browser inputs.
    -   `pygetwindow`: For bringing the browser window to the foreground.

### Architectural Components

-   **`AudioToChat.py` (Orchestrator):** The main application entry point. It initializes all components and manages the primary application lifecycle.
-   **`managers.py`:**
    -   `StateManager`: Holds shared application state (e.g., listening status, auto-submit mode).
    -   `ServiceManager`: Manages the lifecycle of background services like audio and browser automation.
-   **`TopicsUI.py` & `ui_view.py` (UI Layer):**
    -   `UIController` (`TopicsUI.py`): Handles all UI logic and user interactions.
    -   `UIView` (`ui_view.py`): Defines the layout and widgets of the Tkinter GUI.
-   **`topic_router.py`:** Contains the `TopicRouter` class, which decides whether a transcribed topic should go to the UI or be auto-submitted to the browser.
-   **`audio_handler.py`:** Contains the logic for capturing audio from microphones in dedicated threads.
-   **`transcription.py`:** Manages the `faster-whisper` model and the transcription thread.
-   **`browser.py` & `chat_page.py` (Browser Layer):**
    -   `BrowserManager` (`browser.py`): High-level manager for the browser communication thread and submission queue.
    -   `ChatPage` (`chat_page.py`): Encapsulates all low-level Selenium interactions with a specific chat website.
-   **`config.py`:** Central configuration file for all user-specific settings (API keys, paths, selectors, etc.).
-   **`requirements.in` / `requirements.txt`:** Dependency management files.

## 4. Setup and Installation

Follow these steps carefully to set up the project on a new Windows machine.

### Prerequisites

1.  **NVIDIA GPU:** A CUDA-enabled NVIDIA graphics card is required for GPU acceleration.
2.  **NVIDIA Driver:** Install the latest NVIDIA Game Ready or Studio Driver for your GPU.
3.  **CUDA Toolkit:** Install the NVIDIA CUDA Toolkit. This project has been tested with version 12.x. You can download it from the [NVIDIA Developer website](https://developer.nvidia.com/cuda-toolkit).
4.  **cuDNN Library:** Install the NVIDIA cuDNN library that matches your CUDA Toolkit version.
    -   Download cuDNN from the [NVIDIA Developer website](https://developer.nvidia.com/cudnn).
    -   **Crucial Step:** After unzipping the cuDNN folder, you must copy the `.dll` files from its `bin` directory and paste them directly into the `bin` directory of your main CUDA Toolkit installation (e.g., `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin`).
5.  **Python:** Install a stable, 64-bit version of Python (e.g., Python 3.12).
    -   Download from the [official Python website](https://www.python.org/downloads/windows/).
    -   During installation, ensure you check the box **"Add python.exe to PATH"**.
6.  **Google Chrome:** The application is configured to automate Google Chrome.

### Installation Steps

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url>
    cd <your-project-folder>
    ```

2.  **Create and Activate a Virtual Environment:**
    ```bash
    python -m venv .venv
    .venv\Scripts\activate
    ```

3.  **Install Dependencies (A Two-Step Process):**
    This is the most critical part. PyTorch must be installed first with a specific command to enable CUDA support.

    **Step 3a: Install PyTorch for CUDA**
    ```bash
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    ```

    **Step 3b: Install Other Dependencies from `requirements.txt`**
    If `requirements.txt` is not already present, generate it from `requirements.in`:
    ```bash
    pip install pip-tools
    pip-compile requirements.in --output-file requirements.txt
    ```
    Then, install from the generated file:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Browser Setup:**
    You must launch an instance of Google Chrome with remote debugging enabled.
    -   Create a shortcut for Chrome.
    -   Right-click the shortcut -> Properties.
    -   In the "Target" field, add the following flag after `chrome.exe"`, separated by a space:
        `--remote-debugging-port=9222`
    -   Example Target: `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222`
    -   Use this shortcut to launch Chrome before starting the application.

## 5. Configuration

Before running the application, customize `config.py` for your specific setup:

-   **`CHAT`**: Set to the AI service you want to use (e.g., `"Perplexity"` or `"ChatGPT"`).
-   **`DLL_PATHS`**: **Crucial.** Ensure the paths in this list point to the `bin` directory of your installed CUDA Toolkit version (e.g., `r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin"`).
-   **`MIC_INDEX_ME` & `MIC_INDEX_OTHERS`**: Set the correct device indices for your microphones. You may need a separate script to list PyAudio devices to find the correct numbers.
-   **`SCREENSHOT_FOLDER`**: Update this path to a valid folder on your machine where screenshots are saved.
-   **`CHATS` Dictionary**: To add a new AI, create a new entry in this dictionary with its URL, prompt files, and the correct CSS selectors for its UI elements.

Also, ensure your prompt files (`prompt_init.txt`, `prompt_msg.txt`, etc.) are present and contain your desired system prompts.

## 6. Usage

1.  Launch Google Chrome using the special shortcut with remote debugging enabled.
2.  Activate your virtual environment: `.venv\Scripts\activate`
3.  Run the main application script:
    ```bash
    python AudioToChat.py
    ```
4.  The Tkinter UI will appear. Use the "Listen" toggle to start and stop audio capture.
5.  As you and others speak, transcribed topics will appear in the list.
6.  Click on topics to select them. The full text of the last-selected topic appears at the bottom.
7.  Use the "Submit Selected" or "Submit All" buttons to send topics (and any text in the "Context" field) to the configured AI chat.
8.  Use the "New Thread" button to start a fresh conversation with the AI, optionally including any text from the "Context" field.
9.  Use the "Auto-Submit" dropdown to change the submission behavior.

## 7. Troubleshooting

-   **GPU Not Detected (`Using device: cpu` in logs):**
    1.  This is almost always an environment issue.
    2.  Verify the `DLL_PATHS` in `config.py` are correct for your CUDA version.
    3.  Confirm you copied the **cuDNN** DLLs into the CUDA `bin` folder.
    4.  Ensure you followed the two-step dependency installation, installing `torch` with the `--index-url` command *first* in a clean environment.
-   **Microphone Not Working:**
    -   The most common issue is incorrect device indices in `config.py`. Run a script to list your PyAudio devices and find the correct numbers for your headset and your virtual audio cable (e.g., Voicemeeter).
-   **Browser Automation Fails:**
    -   Ensure Chrome was started with the `--remote-debugging-port=9222` flag.
    -   Check that the CSS selectors in `config.py` for the target AI service are still valid, as websites update their structure frequently.Update