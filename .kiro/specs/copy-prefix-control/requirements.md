# Requirements Document

## Introduction

This feature adds a "Keep prefix" checkbox to the UI that controls how copy operations handle the [ME] and [OTHERS] prefixes in topic content. The checkbox will be positioned before the Copy Selected and Copy All buttons, providing users with the option to copy topics with or without their speaker prefixes.

## Requirements

### Requirement 1

**User Story:** As a user, I want to control whether copied topics include speaker prefixes, so that I can get clean content without [ME] or [OTHERS] labels when needed.

#### Acceptance Criteria

1. WHEN the UI loads THEN the system SHALL display a "Keep prefix" checkbox positioned before the Copy Selected and Copy All buttons
2. WHEN the UI loads THEN the "Keep prefix" checkbox SHALL be deselected by default
3. WHEN the "Keep prefix" checkbox is deselected AND I click Copy Selected THEN the system SHALL copy selected topics without [ME] or [OTHERS] prefixes
4. WHEN the "Keep prefix" checkbox is deselected AND I click Copy All THEN the system SHALL copy all topics without [ME] or [OTHERS] prefixes
5. WHEN the "Keep prefix" checkbox is selected AND I click Copy Selected THEN the system SHALL copy selected topics with [ME] or [OTHERS] prefixes included
6. WHEN the "Keep prefix" checkbox is selected AND I click Copy All THEN the system SHALL copy all topics with [ME] or [OTHERS] prefixes included

### Requirement 2

**User Story:** As a user, I want the "Keep prefix" checkbox to only affect copy operations, so that other functionality remains unchanged.

#### Acceptance Criteria

1. WHEN the "Keep prefix" checkbox state changes THEN the system SHALL NOT affect submit operations
2. WHEN the "Keep prefix" checkbox state changes THEN the system SHALL NOT affect topic display in the listbox
3. WHEN the "Keep prefix" checkbox state changes THEN the system SHALL NOT affect the full topic text display
4. WHEN the "Keep prefix" checkbox state changes THEN the system SHALL NOT affect any other UI functionality

### Requirement 3

**User Story:** As a user, I want copied content without prefixes to be properly formatted, so that each topic starts on a new line with clean content.

#### Acceptance Criteria

1. WHEN copying topics without prefixes THEN the system SHALL format each topic starting from a new line
2. WHEN copying topics without prefixes THEN the system SHALL remove only the [ME] and [OTHERS] prefixes while preserving the actual topic content
3. WHEN copying topics without prefixes THEN the system SHALL maintain proper line breaks between topics
4. WHEN copying topics with prefixes THEN the system SHALL maintain the current formatting behavior