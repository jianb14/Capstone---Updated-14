# Four-step booking form implementation plan

> **For agentic workers:** Use executing-plans inline, task by task.

**Goal:** Put event details first and package samples inside selection for both booking forms.

**Architecture:** Keep existing validation, pricing and selection handlers. Reorder and renumber the four panels and indicators; use one shared inline-preview enhancer with the existing image renderer.

**Tech Stack:** Django templates, vanilla JavaScript, CSS, Django tests and Playwright/Edge.

**Spec:** docs/superpowers/specs/2026-11-10-booking-four-step-design.md

## Constraints

Preserve existing workspace edits, selection rules for extras, saved-design/catalog entry points, pricing and server validation. Reuse existing styling and image data; no dependencies. Work directly in the current workspace to keep the user's existing related edits together.

## Review focus

First-step availability and map initialization; keeping selections when collapsing; switching package previews; missing/broken images; saved-design and catalog preselection.

### Task 1: Four-step navigation

- [x] Add a browser regression for event-first navigation, validation, back/next persistence and four indicators on create/edit. Run to confirm failure.
- [x] Reorder panels/indicators and navigation in booking_page.html/customer_profile.html. Update shared stepper geometry in booking_form_components.css. Keep details validation before package selection and design validation before review.
- [x] Update existing tests and customer help that refer to the removed preview step. Run focused Django tests.

### Task 2: Inline package samples

- [x] Extend browser regression with selection, collapse/reopen, switching, keyboard, extras and empty/broken previews. Confirm failure before implementing.
- [x] Add shared setupInlinePreviews(root, imagesForCard, clearPackage) behavior in static/js/booking_form_ui.js. Wire both templates to their current payloads. Use renderPreview and existing theme tokens.
- [x] Run browser tests on mobile/desktop and both themes, inspect screenshots and fix issues.

### Task 3: Verification

- [x] Run the full Django suite and relevant opt-in browser suites; report skips/failures honestly.
- [x] Inspect the final diff and document verification without committing unrelated user changes.
