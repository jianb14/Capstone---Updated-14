# Offline customer update delivery

> Execute inline using executing-plans. User approved showing previously undisplayed updates on next login, separately from notification reads.

**Goal:** An offline approval is shown once on next login and remains unread in the bell until explicitly read.

**Architecture:** Add Notification.bar_shown_at via an additive migration. Return eligible pending notices regardless of the old browser cursor; sign their exact IDs for a customer-only acknowledgement POST. Render first, retain/retry a failed acknowledgement before polling again, and leave cursor/session/navigation guards in place.

**Spec:** docs/superpowers/specs/2026-11-10-customer-update-bar-design.md

- [x] Write and observe a failing logged-out approval regression.
- [x] Add model/migration, signed batch receipts and acknowledgement endpoint; test ownership, CSRF, idempotency, read independence, later arrivals and batches over 20.
- [x] Integrate render acknowledgement/retry with existing client polling and stable per-user receipt storage. Update prior history-suppression expectations and asset versions.
- [x] Add browser login/second-login and acknowledgement-failure regressions; run focused backend/browser checks, schema/syntax checks, independent review, and apply the additive migration to the local app database.

Work in the existing workspace because this extends the authorized uncommitted feature; preserve unrelated edits. No dependency, financial-rule, visual or deployment changes.

Rulings from verification: preserve the receipt across stale-CSRF failures and probe the existing login marker to reach 409 recovery without a reload loop. Watch only a blocking modal's lifetime because a dialog removed immediately after close cannot deliver its queued close event to document. Both regressions were observed before their fixes, then independently reviewed without remaining blockers.

Final result: 34 focused tests passed in 73.086 seconds, including six live-browser tests. Migration 0118 applied locally; schema drift, Django system checks, JavaScript syntax and source/served-script checks pass. Details and practical limits are recorded in docs/customer-update-bar-verification.md.
