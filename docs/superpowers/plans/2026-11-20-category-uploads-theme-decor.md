# Category Uploads and Theme Decor Implementation Plan

> **For agentic workers:** Use the implementation and review workflow task by task. Track results here; do not repeat completed work after compaction.

**Goal:** Count customer uploads under their chosen asset category and add a protected, upload-only Theme Decor category without changing unrelated behavior.

**Architecture:** Store customer uploads independently from the shared catalog. Catalog and upload identities feed existing offer evaluation and limits. Preserve saved upload libraries and booking references using explicit model relationships and a submitted reference snapshot.

**Tech Stack:** Django 5, SQLite/local or configured media storage, Fabric.js 5, existing vanilla JavaScript and CSS, Django tests, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-20-category-uploads-theme-decor-design.md`

## Global Constraints

- Preserve existing booking pricing, payment, deadlines, catalog identity, background, text, and upgrade behavior.
- One placed upload counts once in its immutable upload category; uploading alone counts zero.
- Backgrounds and legacy reference uploads remain uncounted.
- Theme Decor is upload-only, protected, and disabled when absent from an offer.
- Drafts remain saveable; incompatible items must block booking rather than silently disappear.
- JPEG, PNG, WebP only; maximum input 10 MB, working edge 2048 pixels; preserve transparency.
- No AI classification, automatic custom pricing, new approval workflow, dependency installation, or unrelated refactor.

## Review Focus

- Switching offers while uploads remain must preserve the layout and flag disallowed items.
- Foreign IDs, forged category metadata, hidden placements, and malformed color declarations cannot satisfy requirements.
- Booking reference files must survive source design/library deletion.
- Upload-only Theme Decor must not loosen ordinary catalog readiness or text-preset rules.
- Old reference images and background uploads must retain their current behavior.

## Task 1: Server upload identity and offer evaluation

**Files:** `app/models.py`, new `app/canvas_uploads.py`, new upload views and tests, migration after 0121, `app/canvas_builtins.py`, `app/design_validation.py`, `app/offer_editor.py`, `app/design_admin.py`, `app/urls.py`, cleanup integration.

**Interfaces:** `CanvasUpload(owner, category, image, label, colors, width, height)`; `UserDesign.uploads`; `Design.uploads` and `Design.reference_snapshot`. `upload_payload(upload)` returns id, token, src, category_id, category, label, colors, width, height. `evaluate_design(canvas_json, offer, catalog=None, *, owner=None)` counts `_designSource='upload'` with `_uploadId` and `_uploadToken`. `evaluate_saved_design` supplies the design owner. `category_accepts_uploads(category)` excludes Styrofoam Name/text-only categories.

- [x] Write failing upload validation, ownership, mixed-source counting, color, and Theme Decor readiness tests; watch failures.
- [x] Implement server validation, protected image serving, media cleanup and stable payloads; preserve ordinary readiness checks.
- [x] Create the built-in category migration without automatically changing service inclusions or package quantities.
- [x] Run upload tests and existing design requirement/built-in/offer tests.

## Task 2: Canvas library and custom placements

**Files:** `app/views/designs.py`, `app/templates/client/design_canvas.html`, `static/js/design_canvas.js`, `static/js/design_rules.js`, `static/js/design_upgrades.js`, focused category-upload JS and CSS, browser and unit tests.

**Interfaces:** POST upload accepts `image`, `category_id`, `design_offer_id`, optional `design_id`, `label`, and JSON `colors`; response `{upload: payload}`. Server-rendered `canvas_uploads_payload` maps upload IDs to payloads; save payload includes `upload_ids` for the design library. Count metadata includes `_uploadId`, `_uploadToken`, `_designSource`, `_categoryId`. Catalog metadata remains intact.

- [x] Write failing mixed-source JavaScript quantity/upgrade tests and a focused browser upload test.
- [x] Render category upload controls, an upload-only Theme Decor accordion, and a Background tab without the general uploader.
- [x] Upload files through the server, persist/restore personal thumbnails, declare balloon colors, and attach identity on click/drag/duplicate/undo/redo.
- [x] Extend client evaluation and upgrade checks while preserving catalog and legacy references.
- [x] Pass owner to evaluation/save; bind valid library and placement IDs to the saved design.
- [x] Verify Node tests, Django design tests, and desktop/mobile browser behavior.

## Task 3: Booking snapshot and administrator references

**Files:** `app/canvas_uploads.py` snapshot helpers, `app/views/bookings.py`, existing admin references template and relevant booking context, focused booking tests.

**Interfaces:** `snapshot_design_reference(design)` returns immutable submitted offer/layout/custom-placement metadata. `Design.reference_snapshot` and `Design.uploads` retain the submitted images. Existing previews remain available.

- [x] Write a failing booking test for submitted custom breakdown surviving source edits/deletion.
- [x] Save the snapshot and retained upload relationships in the existing booking submission path.
- [x] Show categorized custom uploads and declared colors in the current references section; show a reference mismatch after package changes without altering pricing/statuses.
- [x] Verify historical previews, ordinary booking, and change-request behavior.

## Task 4: Regression verification and review

- [x] Update guidance and assertions that describe the removed general uploader, without rewriting unrelated UI.
- [x] Run migration checks, Django system checks, focused feature tests, JavaScript tests, relevant optional browser tests, then the project test suite.
- [x] Review the full change with a fresh reviewer; fix important findings and rerun affected checks.
- [x] Report exact verification and any unresolved limitations. Leave changes reviewable in the user's current checkout.

## Progress and rulings

- Baseline: current branch `fix/user-facing-error-messages`; tracked files initially clean; preexisting untracked user documentation is unrelated.
- Ruling: execute in the existing checkout to keep the authorized changes visible in the user's IDE; do not merge, publish, or change branches.
- Ruling: preserve ordinary catalog readiness; only Theme Decor can satisfy an offer through uploads without a default asset. This follows the user's latest instruction to preserve existing functionality.
- Ruling: do not automatically convert existing Theme Decor service inclusions, since the approved specification requires review before changing their meaning. Supply a read-only report and preserve existing package quantities.
- User approved the concrete mapping report: convert exact Theme Decor rows in Package 1-B, Package 2, Package 3, Package 4 and Stand B into the built-in category, preserving quantities and optional minimum 0. Migration 0123 is limited to those existing rows.
- Pre-flight: Task 2 consumes Task 1 upload identity; Task 3 consumes Task 1 model relationships. Use the exact interfaces above and keep catalog and upload namespaces separate.
- Baseline passed: 53 existing Django tests and both existing Node rule/upgrade suites. New mixed-source Node tests observed failing before implementation, then passed. New backend/integration checks observed failing before feature support, then 63 focused Django tests passed.
- Browser desktop custom upload, catalog/custom count, undo/redo, save and reopen passed. Mobile test initially collapsed an already-open accordion; correcting the test to open only when collapsed. Existing general upload tests now exercise Background and the dedicated category browser test covers custom uploads.
- Test runner correction: two Django processes briefly shared the default PostgreSQL test database; rerun all affected checks serially. No development database was changed by tests.

- Final review: nine important findings corrected; 106 focused Django checks and seven Node checks passed after the fixes. New category browser check passed after owner/duplicate/source fixes; existing design and inventory browser cases passed.
- Migration verification: 0122 and 0123 applied; category ID 25 retained; exact five approved inclusions mapped; Package 1-A remains without Theme Decor; all existing package offers remain ready.
- Scope ruling: legacy caches without an owner remain compatible; explicit foreign-owner caches are rejected. Cost: old anonymous cache behavior is unchanged.
- Scope ruling: abandoned browser-only uploads expire after 24 hours; saved design and booking references retain their images. Cost: a browser-only draft is not permanent storage.
- Verification correction: the first full run overlapped review changes, causing two mixed-import booking errors. Both passed in a fresh focused run; a clean full run is active. Fifteen unrelated failing methods were reproduced against original HEAD.

- Final full-suite result: 1706 tests; 13 failures, 6 errors, 233 skips. The 15 unique failing methods exactly match the isolated original-HEAD comparison; no new failing methods. Full suite remains non-green for the documented unrelated failures.
- Final browser result: category upload, existing design, and existing inventory checks passed across desktop/mobile and both themes; inspected screenshots after correcting the new card layout.
- Stand B inclusion mapped as authorized; existing disabled stand designer configuration and other unresolved stand setup preserved.
- Automatic approval review rejected deletion of generated baseline sources/ZIP (blocked by policy); scratch artifacts retained in the ignored verification folder.
