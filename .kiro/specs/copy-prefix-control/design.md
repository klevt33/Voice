# Design Document

## Overview

This feature adds a "Keep prefix" checkbox to control how copy operations format topic content. When unchecked (default), copy operations will exclude the [ME] and [OTHERS] prefixes from topics. When checked, the current behavior is maintained with prefixes included.

## Architecture

The implementation follows the existing MVC pattern:
- **View (UIView)**: Adds the checkbox widget and exposes its state
- **Controller (TopicsUI)**: Modifies copy methods to check the checkbox state and format content accordingly
- **Model**: No changes needed as the Topic objects remain unchanged

## Components and Interfaces

### UIView Changes

**New Attribute:**
- `keep_prefix_var`: `tk.BooleanVar` - Tracks the checkbox state (default: False)

**Modified Method:**
- `_create_action_buttons()`: Add the "Keep prefix" checkbox between copy buttons and delete submitted checkbox

**New Method:**
- `get_keep_prefix_state()`: Returns the current state of the keep prefix checkbox

### TopicsUI Changes

**Modified Method:**
- `copy_selected_topics()`: Check the keep prefix state and format messages accordingly

**New Method:**
- `_format_topic_for_copy()`: Helper method to format individual topics based on prefix preference

## Data Models

No changes to existing data models. The Topic class remains unchanged as the formatting logic is handled during the copy operation.

## Error Handling

The implementation reuses existing error handling patterns:
- Empty topic list handling remains the same
- Status message updates follow existing patterns
- No new error conditions are introduced

## Testing Strategy

### Unit Tests
- Test checkbox initialization (default unchecked state)
- Test copy operations with prefix enabled/disabled
- Test that only copy operations are affected by the checkbox

### Integration Tests  
- Test UI layout with new checkbox positioned correctly
- Test copy functionality with various topic combinations
- Test that submit operations remain unaffected

### Manual Testing
- Verify checkbox appears in correct position
- Test copy operations with different checkbox states
- Verify formatting of copied content with and without prefixes

## Implementation Details

### Checkbox Positioning
The checkbox will be positioned between the copy buttons and the "Delete submitted" checkbox:
```
[Copy Selected] [Copy All] [Keep prefix] [Delete submitted] [Submit Selected] [Submit All]
```

### Content Formatting Logic
When `keep_prefix_var` is False:
- Remove `[ME]` and `[OTHERS]` prefixes from topic text
- Maintain line breaks between topics
- Preserve context formatting (if present)

When `keep_prefix_var` is True:
- Use existing formatting logic
- Maintain all prefixes and current behavior

### State Management
The checkbox state is managed locally in the UIView and accessed by the controller when needed. No persistent storage is required as this is a session-based preference.