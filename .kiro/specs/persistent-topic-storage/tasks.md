# Implementation Plan

- [x] 1. Add storage configuration to config.py


  - Add TOPIC_STORAGE_FOLDER configuration variable with default path
  - Include documentation comment explaining the storage feature
  - _Requirements: 3.1, 3.3_

- [x] 2. Create TopicStorageManager class


  - Create new file topic_storage.py with TopicStorageManager class
  - Implement __init__ method that accepts storage folder path
  - Add instance variables for current file handle, session state, and storage folder
  - _Requirements: 1.1, 1.3, 4.1_

- [x] 3. Implement filename generation and directory management


  - Add _generate_filename method that creates timestamp-based unique filenames
  - Add _ensure_storage_directory method that creates directory if it doesn't exist
  - Implement collision handling by appending counter to duplicate filenames
  - _Requirements: 4.3, 4.5, 3.2_

- [x] 4. Implement storage session lifecycle methods


  - Add start_session method that creates new file and writes session header
  - Add end_session method that writes session footer and closes file
  - Add proper error handling for file operations with logging
  - _Requirements: 1.2, 1.3, 1.5_

- [x] 5. Implement topic storage functionality


  - Add store_topic method that writes topic data to active file
  - Format topic data with timestamp, source, and text in structured format
  - Ensure immediate file flush for crash protection
  - Add error handling that doesn't interrupt normal operation
  - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4_

- [x] 6. Integrate storage manager with UIController


  - Add TopicStorageManager instance to UIController class
  - Initialize storage manager with configured folder path from config
  - Call store_topic when topics are added to the topic list in process_topic_queue
  - _Requirements: 1.1, 3.1_

- [x] 7. Connect storage lifecycle to audio monitoring state


  - Call storage manager start_session when audio monitoring starts (Listen=ON)
  - Call storage manager end_session when audio monitoring stops (Listen=OFF)
  - Integrate with existing toggle_listening method in UIController
  - _Requirements: 1.2, 1.3, 4.1, 4.2_

- [x] 8. Add comprehensive error handling and logging


  - Implement graceful degradation when storage operations fail
  - Add detailed logging for all storage operations and errors
  - Ensure storage failures don't affect normal application operation
  - _Requirements: 1.5, 5.1, 5.2, 5.3_

- [x] 9. Create unit tests for TopicStorageManager


  - Write tests for filename generation and uniqueness
  - Test directory creation and error handling
  - Test topic formatting and file writing operations
  - Test session lifecycle management
  - _Requirements: 1.1, 1.2, 1.3, 4.3, 4.5_

- [x] 10. Create integration tests for end-to-end functionality




  - Test complete workflow from topic capture to file storage
  - Test audio state changes triggering file lifecycle
  - Test error scenarios and graceful degradation
  - Verify topics remain independent of UI interactions (submit/delete/copy)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.1_