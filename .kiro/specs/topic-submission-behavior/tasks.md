# Implementation Plan

- [x] 1. Enhance Topic data model with submission status tracking




  - Add `submitted: bool = False` field to the Topic dataclass in TopicsUI.py
  - Ensure the field defaults to False for new topics
  - Verify existing Topic creation and usage remains unchanged
  - _Requirements: 2.2_

- [x] 2. Add checkbox control to UI view




  - Create `delete_submitted_var` BooleanVar instance variable in UIView class (default: False)
  - Modify `_create_action_buttons()` method to include checkbox between Copy and Submit button groups
  - Add checkbox with label "Delete submitted" using ttk.Checkbutton
  - Position checkbox with appropriate padding to maintain visual balance
  - _Requirements: 1.1, 1.2, 3.1, 3.2_

- [x] 3. Implement conditional topic clearing logic in controller




  - Add `get_delete_submitted_preference()` method to UIController that returns checkbox state
  - Modify `clear_successfully_submitted_topics()` method to check preference before clearing
  - When delete_submitted is False: mark topics as submitted instead of removing them
  - When delete_submitted is True: maintain current removal behavior (remove topics)
  - Ensure proper handling of last_clicked_index and full_text_display in both scenarios
  - _Requirements: 1.3, 1.4, 1.5_

- [x] 4. Implement visual indication for submitted topics




  - Modify `update_ui_loop()` method in UIController to apply visual styling
  - Add conditional logic to check if topic is submitted and delete_submitted preference is disabled
  - Apply gray text color (#808080) to submitted topics using itemconfig
  - Ensure visual indication works correctly with existing selection highlighting
  - Test that submitted topics maintain proper color when selected/deselected
  - _Requirements: 2.1, 2.2, 2.4_

- [x] 5. Integrate preference checking in application layer




  - Modify the submission success handler in AudioToChat.py to respect the new preference
  - Update the call to `clear_successfully_submitted_topics()` to work with the new conditional logic
  - Ensure the preference is checked at the right time during the submission flow
  - Test that preference changes take effect for subsequent submissions
  - _Requirements: 1.5_

- [x] 6. Create comprehensive tests for the new functionality




  - Write unit tests for Topic model with submitted field
  - Test UIController methods: `get_delete_submitted_preference()` and modified `clear_successfully_submitted_topics()`
  - Test visual styling application in `update_ui_loop()` for submitted topics
  - Create integration tests for the complete submission flow with both preference settings
  - Test edge cases: preference changes during submission, mixed submitted/unsubmitted selections
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.4_

- [x] 7. Verify UI layout and user experience







  - Test checkbox positioning and visual integration with existing action buttons
  - Verify checkbox state persistence during application session
  - Test that default behavior (delete_submitted=False) works as expected
  - Validate that visual indication is clear and not distracting
  - Ensure all existing topic operations (select, copy, delete) work with submitted topics
  - _Requirements: 3.1, 3.2, 3.3, 3.4_