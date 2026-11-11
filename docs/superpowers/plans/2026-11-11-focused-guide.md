# Focused Guide Implementation Plan

Historical plan. The current behavior follows `2026-11-12-spotlight-tour.md`.

> **For agentic workers:** Use executing-plans for inline implementation.

**Goal:** Replace the broad tour with compact task-aware help in the three main features.

**Architecture:** Read-only feature adapters return the current target/explanation/action. A shared controller handles lifecycle, focus and positioning. Existing feature code owns validation and submissions.

**Tech Stack:** Django, vanilla JavaScript/CSS, existing Playwright/Chrome.

**Spec:** `docs/superpowers/specs/2026-11-11-focused-guide-design.md`

## Constraints and review focus

Manual launch/close only. No global hover tips or unrelated-page guides. Preserve user input, validation authority, modal restrictions and account lifecycle. Avoid obstructing controls. Preserve unrelated manuals and baseline evidence.

## Tasks

- [x] Replace browser contract and observe failures against the old guide.
- [x] Replace content/controller/component/CSS and move launchers into supported features.
- [x] Verify real flows and screenshots, run existing targeted and full-suite checks, and compare baseline failures.
- [x] Obtain independent review, fix verified findings, and update usage/evidence documentation.

## Decisions

- Close is OFF; remove the distracting hover preference/settings.
- Read the current form/checklist/status rather than implementing another validator.
- Continue in the current checkout; the user approved implementation without further questions.

## Execution record

- Observed the old guide fail the new task-aware browser contract before replacement.
- Booking now follows inputs/errors and visible steps; Canvas reads the existing evaluation snapshot; payment controls/status use their actual UI state. No extra backend actions or dependencies.
- Independent review exposed status priority, pending edit wording, hidden checklist state and compact geometry problems. Fixed these and added regressions, including keyboard-sized viewports and custom payment inputs.
- Preserved the original five-item mobile canvas rail. Canvas Guide is in Tools on mobile and beside Save on desktop.
- Targeted existing tests: 48 tests, 3 skips, passed. Full suite: 1510 tests, 11 failures/21 errors/218 skips; all 32 entries match the previously reproduced baseline exactly.
- Final browser verification: **18 tests passed in 100.921 seconds**. Includes real dropdown selection, payment options/acknowledgement without checkout submission, current canvas checklist state, modal focus, partial navigation, compact geometry and existing account-menu behavior.
- Inspected final screenshots for Booking, Canvas, My Payments and checkout, including desktop/mobile and both themes. Evidence and usage are in `docs/site-guide-verification.md` and `docs/site-guide.md`.
- Continuation polish: reproduced payment sibling-option/deadline obstruction, picker advice changing before dismissal, and Escape bubbling from the edit dropdown to its booking modal. Added fixture and actual-route regressions, protected the whole option group/notices, held advice until picker dismissal, and consumed dropdown Escape before the modal handler. Follow-up review found no further concrete issues in the keyboard fix.
- Final screenshots confirm both payment choices and their deadline are visible; the selected booking occasion closes before the next instruction appears. No live transaction, deployment, migration or production data mutation was performed.
