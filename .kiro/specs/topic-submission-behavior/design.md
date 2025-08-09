# Design Document

## Overview

This design implements a configurable topic submission behavior system that allows users to choose whether submitted topics are removed from the list (current behavior) or kept in the list with visual indication. The solution involves adding a checkbox control to the UI, extending the Topic data model to track submission status, and modifying the submission flow to conditionally clear topics based on user preference.

## Architecture

The enhancement follows the existing MVC pattern in the application:

- **Model**: Extend the `Topic` dataclass to include a `submitted` status field
- **View**: Add a checkbox control in the `UIView` class positioned near other topic controls
- **Controller**: Modify `UIController` to handle the new preference and conditional topic clearing logic
- **Application Layer**: Update `AudioToChat.py` to respect the new preference setting

## Components and Interfaces

### 1. Topic Data Model Enhancement

**Location**: `TopicsUI.py` - `Topic` dataclass

**Changes**:
- Add `submitted: bool = False` field to track submission status
- Modify `get_display_text()` method to remain unchanged (visual indication handled in UI rendering)

### 2. UI View Enhancement

**Location**: `ui_view.py` - `UIView` class

**Changes**:
- Add `delete_submitted_var: tk.BooleanVar` instance variable (default: False)
- Add checkbox widget in `_create_action_buttons()` method
- Checkbox label: "Delete submitted"
- Position: Between Copy and Submit button groups for logical association with submission actions

**Alternative Placement Options**:
1. **Primary Recommendation**: In the action buttons area between Copy and Submit buttons - most logical since it directly affects submission behavior
2. **Secondary Option**: Similar to "Show Context" checkbox, positioned in the Topics frame header area using absolute positioning
3. **Tertiary Option**: In the left button area of the Topics frame, after the Delete buttons with appropriate spacing

### 3. Controller Logic Enhancement

**Location**: `TopicsUI.py` - `UIController` class

**Changes**:
- Add method `get_delete_submitted_preference() -> bool` to return checkbox state
- Modify `clear_successfully_submitted_topics()` method to:
  - Check the delete_submitted preference
  - If delete_submitted is False: mark topics as submitted instead of removing them
  - If delete_submitted is True: maintain current removal behavior
- Modify `update_ui_loop()` method to apply visual styling for submitted topics

### 4. Application Layer Integration

**Location**: `AudioToChat.py` - main application file

**Changes**:
- Modify the submission success handler to pass the preference to the clearing method
- No changes needed to the actual call since the logic is encapsulated in the controller

## Data Models

### Enhanced Topic Model

```python
@dataclass
class Topic:
    text: str
    timestamp: datetime
    source: str  # Either "ME" or "OTHERS"
    selected: bool = False
    submitted: bool = False  # NEW: Track submission status
    
    def get_display_text(self):
        source_tag = f"[{self.source}]"
        return f"[{self.timestamp.strftime('%H:%M')}] {source_tag} {self.text}"
```

### UI State Management

- `delete_submitted_var`: BooleanVar controlling the preference (default: False)
- Topic visual states:
  - Normal topics: Default colors (white background, black text)
  - Selected topics: Blue background variations (existing behavior)
  - Submitted topics: Gray text color (#808080) when delete_submitted is disabled

## Error Handling

### Edge Cases

1. **Preference Change During Submission**: If user changes preference while topics are being submitted, the change applies to subsequent submissions only
2. **Mixed Submitted/Unsubmitted Selection**: When both submitted and unsubmitted topics are selected for operations (copy, delete), all are treated equally
3. **Topic Deletion**: Submitted topics can still be deleted manually via right-click or delete buttons

### Validation

- No additional validation required as the preference is a simple boolean toggle
- Existing topic validation and error handling remains unchanged

## Testing Strategy

### Unit Tests

1. **Topic Model Tests**:
   - Verify `submitted` field defaults to False
   - Test topic creation with submitted status

2. **Controller Logic Tests**:
   - Test `clear_successfully_submitted_topics()` with delete_submitted=False (topics marked as submitted)
   - Test `clear_successfully_submitted_topics()` with delete_submitted=True (topics removed)
   - Test visual styling application for submitted topics

3. **UI Integration Tests**:
   - Test checkbox state persistence during session
   - Test preference change affects subsequent submissions
   - Test visual indication appears correctly for submitted topics

### Manual Testing Scenarios

1. **Default Behavior**: Verify checkbox is unchecked by default and topics are kept after submission
2. **Toggle Behavior**: Check box, submit topics, verify they are removed
3. **Visual Indication**: Keep topics enabled, submit some topics, verify gray text color
4. **Mixed Operations**: Select both submitted and unsubmitted topics for copy/delete operations
5. **UI Layout**: Verify checkbox fits well in the existing UI without overcrowding

## Implementation Notes

### Visual Design Decisions

- **Color Choice**: Gray text (#808080) for submitted topics provides clear visual distinction without being distracting
- **Checkbox Position**: Placed between Copy and Submit button groups for direct association with submission behavior, avoiding overcrowding the top control area
- **Label Conciseness**: "Delete submitted" is brief but clear in context

### Backward Compatibility

- Default behavior (delete_submitted=False) changes the current behavior but provides better user experience
- No breaking changes to existing APIs or data structures
- Existing topic operations (select, copy, delete) work unchanged with submitted topics

### Performance Considerations

- Minimal performance impact: only adds boolean field and conditional logic
- Visual styling updates happen during existing UI refresh cycle
- No additional memory overhead beyond single boolean per topic