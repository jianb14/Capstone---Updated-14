# Missed Design Delivery Review Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist missed design delivery issues and require an accountable resolution before booking completion.

**Architecture:** Extend the lifecycle display and processor with actual event-end detection and one review per booking/design revision. Add an admin-only resolution endpoint and reuse existing admin/customer presentation.

**Tech Stack:** Django 5, Python, existing Django templates and async forms, SQLite isolated tests.

**Spec:** docs/superpowers/specs/2026-11-20-design-delivery-review-design.md

## Global Constraints

- Keep booking and payment records intact. No automatic cancellation or completion.
- No new dependencies, refund automation, or redesign.
- Use isolated SQLite test settings, never the configured production test database.
- Execute in the shared working checkout; preserve unrelated user artifacts. Commit and push are authorized by the user's subsequent request.

## Review Focus

- Worker downtime must not let an after-event upload or direct completion hide a missed design.
- Overnight/legacy events must use the same end-time interpretation as existing scheduling.
- Upload deletion and applied revisions must not inherit an inapplicable resolution.
- A retry must not duplicate customer notifications or resolution history.
- Customer-visible notes must be escaped and resolution without fulfilled service must not enable Completed.

### Task 1: Lifecycle and durable delivery evidence

**Files:** app/models.py; app/migrations/0121_design_delivery_review.py; app/booking_lifecycle.py; app/design_delivery_review.py; app/test_design_delivery_review.py.

**Interfaces:** `event_end_at(booking)` returns a site-timezone aware datetime. `lifecycle_display(booking, now=None)` adds `event_ended`, `design_review`, `design_review_required`, `design_late`, and `design_cycle`. `ensure_design_review(booking, now=None)` runs under the booking row lock and persists/alerts once per cycle.

- [x] Write failing tests for end boundaries, overnight/legacy dates, missed-delivery detection, durable review after late delivery, and repeat-safe alerts.
- [x] Run the isolated test module and confirm failures correspond to missing behavior.
- [x] Add review model, delivery deadline snapshot, event-end helper, display state, and processor integration.
- [x] Run the module plus existing deadline tests; expect all passing.

### Task 2: Mutations and completion gate

**Files:** app/design_delivery_review.py; app/views/bookings.py; app/urls.py; app/test_design_delivery_review.py.

**Interfaces:** admin action `resolve-design` uses the existing admin booking action endpoint; fields `design_revision`, `outcome`, `notes`, `delivered_at`, `service_fulfilled`. Resolve using current `lifecycle_display` under the booking row lock. Upload records its deadline snapshot; deletion reopens an online-delivery resolution when the last current image is removed.

- [x] Write failing endpoint tests for late-upload bypass, completion gating, external/late/agreed resolution, invalid/future dates, stale revision, permissions, repeat submits, and deletion reopening.
- [x] Run the endpoint tests and observe intended failures.
- [x] Implement validation, persisted resolution/history/notifications, upload integration, and completion guards.
- [x] Run review, deadline, workspace, design-delivery and change-request regression tests; expect all passing.

### Task 3: Admin and customer presentation

**Files:** existing admin booking workspace templates; client lifecycle/design/profile templates; app/views/booking_workspace.py; app/test_design_delivery_review.py; app/test_design_delivery_review_browser.py.

**Interfaces:** existing `data-async-form` submission and lifecycle context. Render review labels, customer-safe resolution notes, late delivery history, and a bounded resolution form without nested forms.

- [x] Write failing rendered-view tests for missed/overdue/resolved states, late badges, and hidden completion action while unresolved.
- [x] Add existing-style notices and resolution form; preserve existing queue summary interfaces and expose missed reviews in the queue.
- [x] Run meaningful browser checks for admin resolve and customer visibility at desktop/mobile widths.
- [x] Run `manage.py check`, migration consistency, relevant suites and full isolated suite; report any unrelated failures explicitly.
- [x] Obtain a fresh final review, address material findings, and leave the verified changes in the working checkout.

## Completion evidence

See `docs/design-delivery-review-verification.md`. The feature and required booking regressions pass; unrelated full-suite failures were reproduced on the original snapshot. The existing generic booking-action route handles resolution, so no URL change was needed. Migration 0121 is applied locally. The user subsequently requested commit and push.
