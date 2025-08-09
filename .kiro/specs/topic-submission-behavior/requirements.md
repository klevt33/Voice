# Requirements Document

## Introduction

This feature enhances the topic submission behavior in the UI application by providing users with an option to control whether submitted topics are removed from the list or kept in the list. Currently, when topics are submitted from the UI app to the browser, those topics are automatically removed from the UI app. This enhancement will add a configurable option to either maintain the current behavior (remove submitted topics) or keep submitted topics in the list with optional visual indication.

## Requirements

### Requirement 1

**User Story:** As a user, I want to have an option to control whether submitted topics remain in the list after submission, so that I can choose between the current behavior (removal) and keeping topics for reference.

#### Acceptance Criteria

1. WHEN the application starts THEN the system SHALL display a checkbox option labeled "Delete submitted"
2. WHEN the application starts THEN the checkbox SHALL be unchecked by default (keep topics behavior)
3. WHEN the checkbox is unchecked THEN submitted topics SHALL remain in the topic list after submission
4. WHEN the checkbox is checked THEN submitted topics SHALL be removed from the topic list after submission (current behavior)
5. WHEN the user changes the checkbox state THEN the new behavior SHALL apply to all subsequent topic submissions

### Requirement 2

**User Story:** As a user, I want to visually distinguish submitted topics from unsubmitted topics when they are kept in the list, so that I can easily identify which topics have already been submitted.

#### Acceptance Criteria

1. WHEN submitted topics are kept in the list AND a topic has been submitted THEN the system SHALL display the topic text in a different color
2. WHEN a topic is submitted THEN the system SHALL change the topic's text color to indicate its submitted status
3. WHEN the "Delete submitted" option is enabled THEN visual indication SHALL not be applied since topics are removed
4. IF a topic has been submitted THEN the system SHALL use a muted or gray color for the topic text to indicate its submitted status

### Requirement 3

**User Story:** As a user, I want the topic submission behavior option to be easily accessible and clearly labeled, so that I can quickly understand and modify the behavior without confusion.

#### Acceptance Criteria

1. WHEN viewing the UI THEN the checkbox option SHALL be positioned in a logical location near other topic-related controls
2. WHEN viewing the checkbox THEN the label SHALL clearly indicate the behavior ("Delete submitted")
3. WHEN hovering over or interacting with the checkbox THEN the user SHALL understand that it controls post-submission topic visibility
4. WHEN the checkbox state changes THEN the change SHALL take effect immediately for subsequent submissions