# Implementation Plan

- [x] 1. Add keep prefix checkbox to UI


  - Add `keep_prefix_var` as a `tk.BooleanVar` attribute to UIView class with default value False
  - Modify `_create_action_buttons()` method to include the "Keep prefix" checkbox positioned between copy buttons and "Delete submitted" checkbox
  - Add `get_keep_prefix_state()` method to UIView class to return the checkbox state
  - _Requirements: 1.1, 1.2_

- [x] 2. Implement prefix removal logic in copy operations


  - Create `_format_topic_for_copy()` helper method in TopicsUI class that takes a topic and prefix preference, returns formatted text
  - Modify `copy_selected_topics()` method to check keep prefix state and use appropriate formatting
  - Ensure context formatting is preserved regardless of prefix setting
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 3.1, 3.2, 3.3, 3.4_

- [x] 3. Test the implementation




  - Write unit tests for the new `_format_topic_for_copy()` method with both prefix states
  - Write integration tests to verify copy operations work correctly with checkbox in both states
  - Test that submit operations remain unaffected by the checkbox state
  - _Requirements: 2.1, 2.2, 2.3, 2.4_