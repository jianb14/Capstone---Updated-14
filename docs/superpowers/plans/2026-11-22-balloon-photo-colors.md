# Balloon Photo Colors Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, with a final fresh review.

**Goal:** Choose an image before declaring its balloon colors; display those colors on thumbnails and selected canvas photos, with an Edit colors action.

**Spec:** User approved the upload-first proposal on November 22. Photos retain their original appearance; color declarations count against existing offer limits when placed. Existing category uploads, background uploads, inclusion counts and Theme Decor behavior remain intact.

**Architecture:** Reuse the category upload endpoint and introduce an authenticated color-revision endpoint. Editing creates a new private upload with identical image bytes, preserving old designs and booking snapshots. Replace that photo's identities in the current design and its copies as a single undoable action. A shared native dialog handles a local preview, color choices, cancellation and errors for each photo separately.

**Tech Stack:** Django, Fabric.js 5, vanilla JS/CSS, native dialog, Playwright/Edge.

## Global constraints

- No new dependencies or migrations, and no unrelated feature changes.
- Keep Object Color behavior for catalog assets; uploaded photos retain original pixels.
- Never mutate a booked/shared upload's color metadata or share a deletable image path between revisions.
- Include color names and hex values for custom colors; do not rely on swatches alone.
- Cancel/Escape leaves the image and colors unchanged; multi-file selection asks per photo.

## Tasks

- [x] Add failing API tests for owner-only color revisions, immutable originals, independent file storage, and category/offer checks.
- [x] Implement the narrow revision API and verify image bytes and old references remain unchanged.
- [x] Add failing browser checks for upload-first preview, per-photo colors, cancel, visible labels, selection editing, limits, undo/redo and save/reopen.
- [x] Replace the pre-upload palette with the shared preview dialog; add thumbnail badges and Edit colors buttons.
- [x] Connect selected-photo labels and replacement identities to existing canvas history/count/validation hooks.
- [x] Run focused backend/JS/browser regressions, inspect desktop/mobile screenshots, and request a fresh code review.

## Review focus

- Several selected files must not inherit the previous file's chosen colors.
- A failed or cancelled edit preserves current objects and references.
- Undo/reopen must restore the old color declarations through their immutable upload identities.
- Editing one design must not change another saved design or submitted booking.
- Exceeding a color limit must never make an invalid design bookable.

## Decisions and evidence

- Ruling: Edit colors updates the photo and its copies in the current design; the preview explains this. Other designs retain their prior record.
- Ruling: Reject an edit that would exceed the active canvas color allowance with an actionable message. New unused uploads retain the existing upgrade checks when placed.
- UI: Keep the existing neutral canvas style. Use photo previews, named swatches and plain actions, with responsive native dialogs and keyboard focus restoration.

## Execution evidence

- RED: Both new revision API tests returned 404 before the endpoint existed. The new browser regression found the old pre-upload palette.
- GREEN: The 11 upload API tests passed, including independent image bytes/paths, unchanged old colors/design associations, idempotent saves, owner-only access, and invalid/excluded category/design checks.
- Review fixes: Restoring canvas history now restores library IDs; live Fabric images resolve their current source through getSrc() so color limits include them; successful thumbnail edits restore keyboard focus to the replacement action.
- JS RED/GREEN: Added a failing live-image identity regression, fixed the shared resolver while retaining source-origin checks, then passed design_rules, design_upgrades and category-upload serialization/name checks.
- Browser coverage: Upload-first local preview, missing colors, named labels, selected-object editing, duplicate copies, undo/redo, custom hex colors, network failure/retry, focus return, color limit rejection, per-file cancel/Escape, saved readiness/reopen and mobile editing/selection labels. Confirmed the expanded case passes.
- Browser test setup: Reopen the saved page at a mobile viewport instead of toggling an already-active desktop Assets button. Await scheduled layer updates before checking that a rejected duplicate leaves the layer count unchanged.
- Visual inspection: Desktop light and mobile dark previews use the existing canvas theme. The dialog body scrolls independently so its heading and Save/Cancel actions remain accessible; tablet/light coverage is included.
- Final GREEN: Combined 86-check canvas/API/browser regression run passed (82 backend checks and four real-browser cases), 164.575 seconds. The injected storage-relationship exception in the log belongs to a passing rollback test. Logs are in `.booking-followup-check/balloon-color-final.log`.
- Final UI follow-up: Pass the actual triggering Edit button into the dialog so focus restoration also works when the canvas retains focus on mousedown. A fresh reviewer verified the failed-request/retry path at 390×600, including visible footer actions and error scrolling. No remaining findings.
- Final checks: Three JS behavior scripts, JS syntax checks, Django `check`, `makemigrations --check --dry-run`, and `git diff --check` passed. No migration or dependency was needed. The full system suite was not repeated for this scoped change.
