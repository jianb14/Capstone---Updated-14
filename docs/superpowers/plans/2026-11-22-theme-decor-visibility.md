# Theme Decor Visibility Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Put category uploads below catalog images, use a corner X, and hide theme selection when the selected booking items have no Theme Decor inclusion.

**Architecture:** Keep canvas category quotas and upload identities intact. Share an inclusion capability map between server validation and booking/edit screens. Preserve the existing theme requirement for legacy selections without a DesignOffer configuration.

**Tech Stack:** Django, vanilla JavaScript, Fabric.js, Playwright.

**Spec:** User's November 22 corrections; original scope in ../specs/2026-11-20-category-uploads-theme-decor-design.md.

## Global Constraints

- Change only the requested upload placement/removal and theme availability behavior.
- Preserve palette requirements, booking schedule, prices, background uploads and canvas inclusion counts.
- Treat mapped Theme Decor requirements/inclusions as authoritative, including optional minimum 0.
- No database migrations or live booking changes.

## Review Focus

- Switching to a package without Theme Decor submits an empty theme.
- Create, pending edit and approved-booking change proposals use the same rule.
- Mixed selections allow a theme if a selected item includes Theme Decor.
- Unknown legacy selections retain their prior validation.
- Hiding a canvas category does not remove existing canvas objects or reset counts.

### Task 1: Category upload controls

Files: design_canvas.html, canvas_inventory.css, design_canvas.js, canvas_category_uploads.js, test_category_uploads_browser.py.

- [x] Update browser assertions for hidden excluded Theme Decor, catalog-before-upload order and the upper-right X.
- [x] Run to confirm failure, then move controls and update visibility/button styles.
- [x] Verify desktop/mobile upload, counts, undo/redo, save/reopen and background controls.

### Task 2: Booking theme availability

Files: new booking_themes.py, booking_theme_rules.js and tests; views/bookings.py, views/profiles.py, booking_changes.py; booking_page.html, customer_profile.html.

- [x] Add failing tests for configured excluded/included themes, composite selections, legacy fallback and endpoint normalization.
- [x] Add the shared server policy and JSON map; use it in create/edit/change validation.
- [x] Toggle booking/edit theme groups, errors, submitted values and review rows from the same map; keep colors required.
- [x] Verify theme switching in a browser and relevant booking/change regression suites.

### Task 3: Final verification

- [x] Review the narrow diff, run Django checks and relevant JS checks.
- [x] Record commands/results and any limitations; report the user-visible changes.

## Execution ledger

- Ruling: An explicitly configured selection allows theme choices if any selected offer includes Theme Decor. Unconfigured extras cannot enable it for an excluded configured package. Entirely legacy selections keep their existing requirement, avoiding unrelated booking changes.
- Ruling: Editing a previously themed booking may continue to show a Theme Removed row in the existing comparison review. The Step 3 choices and submitted theme are empty for an excluded offer. This preserves the established review behavior.
- RED: Canvas browser failed because excluded Theme Decor remained visible. Booking API tests failed because blank excluded themes were rejected and stale themes persisted. The booking browser likewise reproduced visible chips for the plain package.
- GREEN: 184 related backend tests passed (booking create/edit/change, palette, price/logistics, design requirements and category uploads). Five JavaScript scripts passed, including 4 user-error tests. Django system checks passed and no migrations were generated.
- Review: A fresh reviewer identified partial pending edits that switch packages without design keys. Added a failing endpoint regression, then cleared only the theme when that selection changes to an excluded offer; stored palette and unchanged legacy submissions are preserved. Follow-up review found no remaining issue.
- Browser regression run: 32 backend checks and four existing canvas/saved-design browser cases passed. The expanded theme browser exposed an overly strict test expectation that hid the existing Theme Removed comparison; corrected the assertion without changing that review behavior.
- Live read-only check: Package 1-A excludes Theme Decor; Package 1-B, 2, 3, 4 and Stand B include it. Local HTTP server returned 200.
- Final GREEN: All 7 focused booking-theme tests passed, including the new partial-edit regression. The expanded Edge browser case passed for create, pending edit and paid change request, desktop/mobile, with the existing downgrade confirmation retained. Test fixtures were prepared before Playwright's event loop; the browser explicitly acknowledges the existing paid downgrade dialog and dismisses stale test notifications before screenshots.
- Final browser evidence: Category upload (including X removal without altering placed-object counts), inventory search/layers, design save/reopen/undo, saved-design fixed-offer navigation, and theme visibility/create/edit/change checks all passed. Screenshots inspected in the system temp directory.
- Final checks: Django `check`, `makemigrations --check --dry-run`, JS behavior/syntax checks, and `git diff --check` passed. No migration was needed. The full system suite was not repeated for this narrow refinement; relevant booking/design regression suites were used.
