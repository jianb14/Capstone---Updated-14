# Booking Change Feedback Implementation Plan

> **For agentic workers:** Use executing-plans to implement in this session.

**Goal:** Give customers accurate booking confirmation and payment feedback before they spend time editing.

**Architecture:** Extend the existing owner-checked change-request GET response for AJAX preflight. Share the payment gate with POST. Use fresh payment totals in booking_changes.js and the existing AppToast dialog for estimated excess; retain final-quote enforcement.

**Tech Stack:** Existing Django, templates, JavaScript, AppToast, Playwright.

**Spec:** docs/superpowers/specs/2026-11-10-booking-change-feedback-design.md

## Constraints and review focus

English UI; no new dependency, refund policy or migration; leave earlier error-page changes intact. Check ownership, cache freshness, pending versus verified funds, no-excess partial payments, cancellation/selection retention and final-quote acknowledgment. Work in current checkout; no deployment or commits.

## Task 1: Early eligibility and accurate copy

- [x] Write request tests for fresh GET eligibility, payment variants, ownership and POST enforcement; observe failure.
- [x] Extend app/views/changes.py and static/js/booking_changes.js; integrate the check in customer_profile.html before prompting for a reason.
- [x] Update booking_page.html confirmation copy and invalidate the changed JS cache version.
- [x] Run focused tests to green.

## Task 2: Estimated excess warning

- [x] Write browser tests for early blocking, stale page data, downgrade cancel/continue, partial-payment no-warning and pending edit behavior; observe missing behavior fail.
- [x] Add the existing-style confirmation dialog to selection/review transitions using live entry payment totals, and retain final-quote acceptance safeguards.
- [x] Run request and real-browser checks; review desktop/mobile screenshots and keyboard controls.

## Task 3: Regression verification and independent review

- [x] Run related booking/payment tests and the full suite. Compare unrelated failures with the documented baseline.
- [x] Request an independent review and resolve substantive issues.
- [x] Record results and limitations.

## Verification

18 request/payment regression tests and 2 real-browser tests pass. Full suite: 1,490 tests, 13 failures and 2 SQLite errors, with the same failing identifiers as the documented baseline. See docs/booking-change-feedback-verification.md for scenarios, commands and limits. Prior error-page changes were preserved. No commits or deployment performed.
