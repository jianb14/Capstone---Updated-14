# Spotlight feature tour

The user's latest instruction supersedes the task-aware assistant: explain the main interface areas with Next/Back and a bright focus box while dimming everything else. No form completion, missing-field coaching, automatic advancement, or actions on the user's behalf.

## Approved behavior

- Keep local Guide launchers for Booking/My Bookings, Canvas and Payments. No autoplay, per-visit chooser, broad public/auth tours or hover settings.
- Starting Guide opens a modal, read-only tour of visible interface regions. A dark scrim has a rounded transparent spotlight around the current region; a compact explanation panel has progress, Back, Next/Done and Close.
- Only Next/Back changes the selected explanation. Filling fields or new validation does not advance it. Tour buttons never click a target, change a booking step, open checkout or save a design.
- Background clicks and keyboard focus stay out of the application while the tour is open. Escape closes only the tour, preserving any underlying booking/native dialog. Restore the launcher focus and the existing scroll lock when closing.
- Explain what each region is for, rather than instructing the user to perform a transaction. Use only current visible targets and skip unavailable regions.
- Scroll offscreen regions into view; clip spotlight bounds to the visible viewport/scroll container. Support desktop, tablet, 320px phones, both themes and reduced motion. Keep tour navigation within the viewport.
- If a target disappears or the account/modal context changes, close cleanly. No automatic restart.

## Implementation constraints

Reuse the shared component and local launchers. Use native dialog focus containment and an SVG spotlight mask, no new dependency/backend endpoint. Remove task adapters, hover storage and canvas evaluation/save hooks added only for the old assistant. Preserve unrelated manuals and backend behavior.

## Verification

Test manual start/no autoplay, Next/Back/Done, dimmed background with an actual transparent focus hole, background click blocking, no required input/automatic advance, keyboard containment/Escape/focus restore, native/custom modals, skipped/removed targets, partial navigation, clipping/resize and screenshot quality on real feature pages. Run existing relevant tests and compare the complete-suite failure set with the recorded baseline.
