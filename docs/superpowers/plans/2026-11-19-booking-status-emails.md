# Booking Status Emails Implementation Plan

> **For agentic workers:** Use executing-plans to implement inline, with TDD.

**Goal:** Send customer booking lifecycle emails without breaking booking operations.
**Architecture:** Observe new status history entries, snapshot content, send after commit.
**Tech Stack:** Django signals, transaction.on_commit, existing Django email backend.
**Spec:** docs/superpowers/specs/2026-11-19-booking-status-email-design.md

## Constraints and review focus

Preserve in-app notifications and unrelated workspace changes. Test rollback, repeat
saves/history-only entries, each supported status, recipient isolation, provider errors,
payment amount/deadline, expiry worker, and correct authenticated booking links.

## Task 1: Customer lifecycle emails

- [x] Add failing behavior tests in app/test_booking_status_email.py and run them.
- [x] Add app/booking_status_email.py and register receivers in app/apps.py.
- [x] Add optional origin setting in Project/settings.py and document in docs/email.md.
- [x] Run focused tests, related booking/payment tests, full isolated suite and checks.
- [x] Review the diff and record results; do not commit unrelated user changes.

Results: docs/booking-status-email-verification.md. Final related run: 158 passed.
Full suite has documented failures; two new-test failures from its initial snapshot
were fixed and verified in the final related run. Reviewer finding fixed with two
regression tests; final review has no remaining findings.
