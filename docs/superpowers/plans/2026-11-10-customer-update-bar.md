# Customer update bar implementation plan

> Execute inline using executing-plans. Design and scope are approved.

**Goal:** Display the approved full-width bar, with grouping at exactly two new updates.

**Architecture:** Add customer_updates.py for signed positions, conservative event classification and an owner-scoped incremental payload. Extend the existing feed endpoint and navbar bootstrap. Add a shared bar presenter integrated with existing notification polling, reads and navigation. Preserve all unrelated workspace changes.

**Stack:** Django, vanilla JavaScript/CSS, Django tests and Playwright/Chrome.

**Spec:** docs/superpowers/specs/2026-11-10-customer-update-bar-design.md

- [x] Write failing endpoint tests for bootstrap/no historical replay, every event class, owner/role checks, invalid/cross-user cursor, exact 1/2/3 counts, read behavior and batches exceeding 20.
- [x] Implement classification and incremental payload; extend feed/context/navbar without changing normal pagination.
- [x] Write a browser regression for exact two grouping, repeated polls/reload, callbacks, failure recovery, timing, hidden tab, focus and responsive themes; observe failure.
- [x] Implement shared bar CSS/presenter and integrate polling/read/navigation, retaining existing admin behavior. Bump shared asset versions.
- [x] Run focused notification tests and browser regressions, inspect screenshots and request one independent review. Document checks and remaining prior full-suite failures.

Verification: 30 focused tests pass, including four live-browser tests, using disposable file-backed SQLite/WAL with immediate transaction entry for concurrent HTTP checks. See docs/customer-update-bar-verification.md for the test-database limitation and prior suite results.
