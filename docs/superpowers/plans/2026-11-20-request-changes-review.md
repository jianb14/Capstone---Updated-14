# Request Changes Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Show original/requested booking differences and an accurate payment-aware estimate before a change request is submitted.

**Architecture:** Extend the existing owner-checked change endpoint with a read-only review POST. Reuse prepare_proposal and shared Decimal payment calculations so review agrees with the final quote. Keep the two existing cards and decorate their request-mode rendering through a focused review script.

**Tech Stack:** Django, vanilla JavaScript, existing account-page lifecycle, Playwright/Chrome.

**Spec:** docs/superpowers/specs/2026-11-20-request-changes-review-design.md (approved including payment clarification).

## Global Constraints

- Preserve the existing approval, payment, availability, and nonrefundable-excess policies.
- Show complete proposed details, changed/added/removed values, and reference-picture differences.
- Use saved original prices; never fabricate historical line prices or item-level payment allocations.
- All remaining/additional/excess amounts in review are estimates.
- Preserve ordinary pending-booking edits, new bookings, and unrelated workspace edits.
- No new dependency or database migration.

## Review Focus

- Partial payment must reconcile remaining total with change top-up plus later booking balance.
- Historical prices and unchanged fee policies must match server proposal calculation.
- Failed/stale previews and pending verification must never leave an enabled submission using old amounts.
- Closing/reopening or switching between request and direct-edit modes must clear state.
- Image-only changes, optional removals, pin-only changes, and reverted values must remain distinguishable.

## Task 1: Authoritative original data and payment-aware review

Files: app/booking_change_review.py (new), app/booking_changes.py, app/views/changes.py, app/test_booking_change_review.py (new).

Interfaces: review_baseline(booking) -> JSON-ready original data/version; payment_amounts(original, revised, paid) -> Decimal amounts; review response includes original, proposed, breakdown, payment, and has_changes. Existing change endpoint GET adds review_original; POST review_only=1 returns a preview without creating a request or uploading files. original_version is checked on preview/submission when supplied.

- [x] Add tests for unpaid/partial/full/higher/lower/equal amounts, summing verified credited payments only, owner access, stale original, no changes, and read-only preview.
- [x] Run .venv/Scripts/python.exe manage.py test app.test_booking_change_review --settings=Project.test_settings --noinput; observe missing-feature failures.
- [x] Extract the shared payment arithmetic without changing existing callers' return keys and add baseline/preview serialization with saved amounts and fallback.
- [x] Run the new suite plus existing booking-change/payment tests; require passing output.

## Task 2: Inline comparisons and payment breakdown

Files: static/js/booking_change_review.js (new), static/js/booking_changes.js, app/templates/client/customer_profile.html, static/css/booking_changes.css, app/test_booking_change_review_browser.py (new).

Interfaces: window.BookingChangeReview.configure(original), reset(), review() -> Promise<boolean>, render(); use the baseline/preview from Task 1. Change-request prefill comes from original.fields and original.images. Existing populateEditSummary renders normally for direct edits; request rendering uses authoritative preview. Next to review fetches a preview; failed/no-change previews disable submit. Submit retains existing server enforcement.

- [x] Write and run a browser test showing missing comparisons/payment breakdown for a partial-paid upgrade.
- [x] Implement request-only current/requested rows and image status using safe text rendering, server-calculated prices/payment breakdown, and retryable review feedback.
- [x] Add refreshed original prefill, stale-data detection, no-change gating, and cleanup on modal close/reopen.
- [x] Verify reverting values, pin/optional/image changes, price fallback, unpaid and fully paid cases, and pending verification arriving during editing.
- [x] Run browser checks at 1440px and 390px in light/dark themes, inspect screenshots, and check keyboard/navigation and no horizontal overflow.

## Task 3: Verification and review

- [x] Run focused Django regression suites for changes, checkout, payment overview, and normal booking edits plus manage.py check and JavaScript syntax checks.
- [x] Inspect only this task's diff against saved pre-edit copies, preserving unrelated edits.
- [x] Request independent review against the approved spec and fix substantive findings with regression tests.
- [x] Record verification and limitations in docs/booking-change-review-verification.md and mark this plan complete.

## Execution rulings

- User explicitly approved implementation; continue directly without another approval round.
- Work in the current feature checkout because it contains extensive existing uncommitted work needed by the running app. Save pre-edit copies for a focused review; do not stage or commit unrelated work.
- Reuse the current endpoint for read-only preview rather than introducing a separate route. Preview receives draft values, runs existing proposal validation, and returns before request/image creation.

## Completion

All tasks complete. Final evidence: 127 booking tests passed (7 browser tests included); request-protection suite: 24 passed, 2 skipped. Independent final review: no remaining substantive findings. See docs/booking-change-review-verification.md for exact commands and local test limits.
