# Design Document

## Overview

The stealth URL navigation enhancement replaces the current bot-detectable `driver.get()` navigation method with alternative approaches that simulate more human-like browser behavior. The design focuses on implementing multiple stealth navigation techniques with graceful fallback to manual navigation, while maintaining the existing application architecture and browser interaction patterns.

## Architecture

### Current Navigation Flow
The existing navigation occurs in `ChatPage.navigate_to_initial_page()` method, which:
1. Checks if current domain matches target domain
2. If different, uses `driver.get(nav_url)` to navigate
3. Waits for URL to contain target domain

### Enhanced Navigation Flow
The enhanced flow will:
1. **Window Activation**: Use existing `focus_browser_window()` logic to activate browser
2. **URL Evaluation**: Check if navigation is needed (same as current)
3. **Stealth Navigation**: Attempt clipboard-based address bar navigation
4. **Verification**: Verify navigation success
5. **Manual Fallback**: Provide user guidance and wait for manual navigation if stealth method fails

## Components and Interfaces

### 1. Enhanced ChatPage Navigation Methods

#### `navigate_to_initial_page()` - Modified
- **Purpose**: Main entry point for navigation with stealth capabilities
- **Changes**: 
  - Add window activation before navigation check
  - Replace direct `driver.get()` with stealth navigation orchestrator
  - Add manual fallback integration

#### `_navigate_via_address_bar_clipboard()` - New
- **Purpose**: Navigate using clipboard-based address bar interaction (most reliable stealth method)
- **Implementation**: 
  - Focus address bar using Ctrl+L
  - Select all existing content with Ctrl+A
  - Copy target URL to clipboard using `pyperclip.copy()`
  - Paste URL using Ctrl+V (same reliable approach as message submission)
  - Press Enter to navigate
- **Advantages**: 
  - Reuses proven clipboard approach from existing message submission
  - Most human-like navigation method
  - Bypasses many bot detection systems
  - Reliable and fast execution

#### `_verify_navigation_success()` - New
- **Purpose**: Verify that navigation completed successfully
- **Implementation**: Check current URL domain matches expected domain
- **Timeout**: 10-second maximum wait with 0.5-second intervals

#### `_initiate_manual_navigation_fallback()` - New
- **Purpose**: Handle manual navigation when automatic methods fail
- **Implementation**:
  - Log clear instructions for user
  - Call UI callback to update status message
  - Monitor URL changes to detect manual completion
  - Return success after detection or timeout

### 2. Browser Manager Integration

#### `focus_browser_window()` - Existing
- **Usage**: Called before any navigation attempt
- **No Changes**: Reuse existing implementation

#### UI Status Updates - New Integration
- **Purpose**: Communicate manual navigation needs to user
- **Implementation**: Use existing `ui_update_callback` mechanism
- **Message**: "Please navigate to [URL] manually in your browser"

### 3. Configuration Integration

#### Stealth Navigation Settings - New
```python
# Add to CHATS configuration
"stealth_navigation_enabled": True,
"manual_navigation_timeout": 60,  # seconds
"navigation_retry_attempts": 3
```

## Data Models

### Navigation Result Enum
```python
class NavigationResult:
    SUCCESS = "success"
    FAILED_NEED_MANUAL = "manual_required" 
    FAILED_ERROR = "error"
```

### Single Stealth Method Approach
- **Primary Method**: Clipboard-based address bar navigation
- **Fallback**: Manual navigation with user guidance
- **Rationale**: Proven clipboard approach + simplicity over multiple complex methods

## Error Handling

### Navigation Method Failures
- **Approach**: Single stealth method catches its own exceptions
- **Logging**: Log failure reason at INFO level
- **Fallback**: Immediate transition to manual navigation on failure
- **Simplicity**: No complex retry logic or multiple method attempts

### Connection Errors
- **Integration**: Use existing connection monitoring from `ConnectionMonitor`
- **Behavior**: Connection errors during navigation trigger reconnection flow
- **Recovery**: Retry navigation after successful reconnection

### Timeout Handling
- **Navigation Timeout**: 10 seconds per stealth method attempt
- **Manual Navigation Timeout**: 60 seconds (configurable)
- **Behavior**: Assume success on manual navigation timeout to avoid blocking

## Testing Strategy

### Unit Testing Approach
1. **Mock WebDriver**: Test clipboard-based navigation method with mocked Selenium driver
2. **URL Validation**: Test domain checking and URL parsing logic
3. **Clipboard Integration**: Test clipboard operations and keyboard shortcuts
4. **Fallback Logic**: Test manual navigation fallback triggers correctly

### Integration Testing Approach  
1. **Real Browser Testing**: Test clipboard-based navigation with actual Chrome instance
2. **Bot Detection Testing**: Verify address bar method avoids ChatGPT/Perplexity detection
3. **Manual Fallback Testing**: Test user workflow when automatic navigation fails
4. **Existing Functionality**: Ensure no regression in other browser interactions

### Test Scenarios
1. **Same Domain**: Navigation skipped when already on correct domain
2. **Different Domain**: Clipboard-based stealth navigation attempted and verified
3. **Stealth Method Fails**: Manual fallback activated with proper user messaging
4. **Connection Loss**: Navigation integrates with reconnection handling
5. **Window States**: Navigation works with minimized/inactive browser windows

## Implementation Sequence

### Phase 1: Core Implementation
1. Implement clipboard-based address bar navigation method
2. Modify `navigate_to_initial_page()` to use stealth method
3. Add window activation before navigation
4. Implement manual navigation fallback with UI status integration

### Phase 2: Testing & Refinement
1. Test against ChatGPT and Perplexity bot detection
2. Refine timing parameters for clipboard operations
3. Add comprehensive error handling
4. Validate no regression in existing functionality

## Security Considerations

### Bot Detection Avoidance
- **Human-like Timing**: Add realistic delays between clipboard operations
- **Proven Approach**: Reuse clipboard method that works reliably for message submission
- **Address Bar Focus**: Most natural way humans navigate to URLs

### Privacy & Safety
- **No Data Exposure**: Navigation methods don't expose sensitive information
- **Existing Security**: Maintain all existing security practices
- **User Control**: Manual fallback ensures user maintains control

## Performance Impact

### Minimal Overhead
- **Startup Impact**: Additional 1-2 seconds for clipboard-based navigation
- **Memory Usage**: Negligible increase from single new method
- **CPU Usage**: Minimal increase from clipboard operations and timing delays

### Optimization Strategies
- **Single Method**: No complex retry logic or multiple method attempts
- **Fast Execution**: Clipboard operations are faster than typing simulation
- **Quick Fallback**: Immediate transition to manual navigation on failure