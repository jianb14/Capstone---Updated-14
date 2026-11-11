# Spotlight Feature Tour Implementation Plan

> **For agentic workers:** Use executing-plans for inline execution.

**Goal:** Replace task coaching with a manually advanced spotlight feature tour.

**Architecture:** Static feature descriptions identify visible interface regions. One native dialog owns an SVG dimming mask, target highlight, explanation and navigation; the existing page owns all application actions. Account navigation and modal changes dismiss obsolete tours.

**Tech Stack:** Django templates, vanilla JavaScript/CSS, SVG and existing Playwright/Chrome.

**Spec:** `docs/superpowers/specs/2026-11-12-spotlight-tour-design.md`

## Constraints and review focus

- Never start or advance automatically, require answers, or trigger target actions.
- Preserve native/custom modal focus, form values, scroll locks and launcher focus.
- The focus hole must remain clear while the rest of the page is dim; resize/scroll must not misalign it.
- Skip hidden controls and close if the selected target is removed or its context changes.
- No dependency, production data mutation, admin feature, manual-artifact edit, or unrelated backend fix.

## Tasks

- [x] Replace browser contract; observe failure against the task assistant.
- [x] Replace task content/controller/UI with the native-dialog spotlight tour; remove obsolete canvas-only hooks and refresh asset versions.
- [x] Verify real-page screenshots, keyboard/modal behavior, empty/pre-filled form independence, mobile clipping and existing account-menu behavior.
- [x] Request independent review, fix verified issues, run relevant/full checks and update usage/evidence documentation.

## Decisions

- Native dialog provides background focus containment. SVG mask leaves the highlighted target at its original brightness; the dialog surface blocks all application clicks during the tour.
- No arrow cursor, field-focus actions, typewriter effect or preference settings are needed for the requested feature explanation.
- User explicitly authorized this concrete behavior and implementation; no additional design confirmation is needed.

## Execution record

- Observed the new Next/Back contract fail against the old assistant before implementation. The first six spotlight tests passed, including pixel-brightness verification of the clear target/dim surroundings.
- Real Booking, Canvas, Payments and checkout tours passed with screenshots at 1440, 768, 390 and 320px and both themes. The existing account-menu browser test also passed (9 tests before adding shortcut isolation coverage).
- Independent review found Canvas document shortcuts could still run behind the native modal. Reproduced the failure, stopped keydown propagation without preventing native button defaults, and added both a regression and an actual Fabric-object preservation check. Keyup remains available to release any previously held pan state. Follow-up review reported no remaining P1/P2 findings.
- Final browser run: **10 tests passed in 79.173s**. Expanded real-page responsive check: **1 test passed in 22.741s**, including desktop/mobile payments and checkout.
- Complete suite: **1511 tests, 442.643s, 11 failures/21 errors/219 skips**. All 32 failure/error entries exactly match the previously reproduced baseline. No new full-suite failure was introduced; failure names and evidence are in `docs/site-guide-verification.md`.
- Removed obsolete canvas-only task-guide hooks. Existing app data/actions, manual artifacts and admin functionality were preserved. No new dependency, live transaction, deployment or database migration was required.
