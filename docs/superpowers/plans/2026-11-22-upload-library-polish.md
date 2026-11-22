# Personal Upload Library and Canvas Polish

> Use superpowers:executing-plans inline; request a final fresh review.

**Goal:** Compact upload cards with one section label, contained color dots, small actions; a centered neutral modal consistent with system dialogs; compact selected-photo toolbar; disabled Object Color for uploaded photos; reusable private uploads across designs.

**Spec:** User's November 22 screenshots and explicit correction request. Preserve original photos, category counts, color limits, background controls and historical references.

**Architecture:** Add nullable `CanvasUpload.library_removed_at`. Visible personal uploads persist until explicitly removed; removal hides them while retaining files for saved/booking references and allowing a 24-hour cleanup grace period. Canvas payloads include the owner's visible library plus current design references. Color revisions hide the previous library version without mutating historical image/color records. Session undo/redo continues to restore old immutable identities; a fresh editor loads the current personal library.

**UI:** Keep current system typography, borders and light/dark surfaces. One Custom uploads heading per category. A single card contains image, filename, unlabeled swatches with accessible names and a compact Edit colors action. Checkbox and hover states use neutral outlines; swatches keep their actual colors. Native dialog explicitly centers and has a plain SVG close action, circular custom picker and fixed actions. Uploaded selections disable all Object Color inputs/swatches without changing catalog asset behavior.

- [x] Add failing API tests for cross-design visibility, ownership, soft removal, grace cleanup and immutable references.
- [x] Implement migration, library loading, removal and revision retention; verify backend behavior.
- [x] Add browser assertions for compact card containment, centered modal, neutral checkbox styling, disabled Object Color, toolbar width, responsive/light/dark behavior and cross-design reuse.
- [x] Update only related templates, category JS, canvas controls and scoped styles.
- [x] Run relevant backend/JS/browser checks, inspect full-page screenshots, get a fresh review and apply the additive migration.

## Review focus

- Private libraries must never include another account's photos.
- Removing a library entry must not remove placed images or historical references.
- Legacy saved layouts must not resurrect globally removed library cards on a fresh load.
- Library revisions retain old identities for history and old designs.
- Native controls, recent swatches and keyboard input all respect uploaded-photo disabling.

## Decisions

- User requests are specific and already authorize these corrections; no extra design approval is needed.
- The modal surface stays opaque like other system dialogs. Color-option backgrounds stay transparent, with neutral hover/selection indicators.
- A fresh editor uses the live personal library; undo/redo within a session retains its existing historical library behavior.

## Evidence

- RED: New library tests reproduced missing cross-design uploads, absent removal endpoint, and deletion of old visible library photos. The browser reproduced the off-center modal.
- GREEN: 14 upload/API tests passed. The expanded browser case passed compact contained cards, no repeated tag/text color labels, named accessible dots, disabled native/inert Object Color controls, unchanged catalog controls, centered neutral dialog, toolbar width, immutable edits/history, save/reopen, fresh-design reuse, and responsive/light/dark screenshots.
- Migration0124 applied successfully to the local application database; no existing data is removed. Live CSS and JS endpoints returned 200 and the current source markers.
- Fresh read-only review found no blocking issue. Its minor SVG-close note was corrected using the existing ci-close icon.
- Combined regression run: 89 checks passed; an additional toolbar test exposed a pre-existing assumption that every SVG was an inventory icon. HEAD already includes a Guide icon with stroke 1.7 and no symbol use, while inventory icons use 1.6. Scoped that assertion to svg.inventory-icon, preserving both product icon styles, and reran the toolbar behavior checks.
- Final GREEN: The corrected toolbar case passed all light/dark and desktop-width text/font, arrangement, duplicate/undo and object-control checks (24.485 seconds). All 90 targeted checks passed across the combined run and focused rerun. Three JS behavior scripts, syntax checks, Django system checks and migration consistency checks also passed.
- Inspected full-page desktop selection and mobile library/card screenshots, plus light/dark centered dialog previews. The actual local server served the current CSS/JS with HTTP 200.
- No full-system test suite was repeated. No unrelated pricing, scheduling, payments, booking theme gating or background-upload behavior was changed.
