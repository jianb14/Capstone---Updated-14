# Customer update bar verification

Implemented the approved full-width customer bar below the navbar. One new eligible event shows its own message/action; **two or more** show `N new updates` and open the existing notification panel. Bars never stack. Dismissing or auto-hiding does not mark notices read.

Scope includes booking approval/confirmation/decline/cancellation/expiration, payment verification/rejection, change quote decisions/deadlines and admin design delivery. Arbitrary announcements, chat/concerns, submission receipts, review prompts and payment reminders do not trigger it. No migration or booking/payment rules changed.

## Checks

- API regressions cover every agreed event class, exact 1/2/3 counts, history suppression, owner/role enforcement, signed cursor validation, unchanged unread totals and 31-arrival batches.
- Browser checks cover a payment action opening its actual payment detail and marking only that notice read; guests have no bar; grouped action opens the bell without reading notices.
- Browser checks also cover repeated polls, refresh and full-page navigation without replay, request failure recovery, deferral while typing in a modal, focus pause, hidden-page polling, eight-second dismissal, keyboard dismissal and refreshing a stale tab after another sign-in.
- Screenshots inspected at 1440px, 390px and 320px in light/dark themes. The bar spans the viewport, follows the actual navbar height and does not move the page. Artifacts: `.booking-followup-check/customer-update-bar/grouped-*.png`.
- Django system check, JavaScript syntax checks and `git diff --check` pass.
- Independent review findings about fresh-login history, approval destinations and stale tabs were addressed; follow-up review found no remaining blocker.

## Browser database isolation

The normal `Project.test_settings` in-memory SQLite runner intermittently fails concurrent HTTP requests with `OperationalError('cannot start a transaction within a transaction')`, captured using Django's `got_request_exception` signal on `/notifications/<id>/read/`. It also produced page-navigation/read failures during combined runs. A focused run of 28 tests passed, but this is not evidence that shared in-memory connections are reliable for browser concurrency.

File-backed WAL alone also exposed `OperationalError('database is locked')` on `/my-payments/` while the read-notification POST ran concurrently. Django 5 starts SQLite atomic blocks with deferred `BEGIN`, which can fail when upgrading a read transaction to a write transaction.

The final combined verification uses a unique disposable SQLite file under `.booking-followup-check/customer-update-bar/`, enabling WAL and `BEGIN IMMEDIATE` on test connections. This gives live-server threads separate connections and reserves a writer before a read/modify/write transaction, avoiding SQLite lock-upgrade races. It uses `Project.test_settings` otherwise; no production database or application transaction behavior is changed. Both browser opt-ins are enabled. The ignored local runner is `.booking-followup-check/customer-update-bar/verify_updates.py`; run it with `.venv/Scripts/python.exe`. It preserves its uniquely named fixture database to avoid Windows teardown locks.

Final combined result: **30 tests passed in 52.826 seconds** (26 backend/routing tests and four live browser tests), with no server exceptions reported. The runner exited with status 0. Local source and served static-file copies have matching hashes.

## Approved navigation follow-up

A visible bar now survives same-tab navbar navigation and reload with its remaining display time, rather than restarting at eight seconds. The presenter saves a one-shot user/login-scoped handoff on pagehide and restores the single/grouped message. Loading time is excluded; handoffs older than one minute are discarded. Back/Forward cache restoration also reloads the latest notification cursor to avoid counting already-delivered events again. Modal deferral and hover/focus/hidden-page pauses remain in place.

The new regression first failed because the next page's bar was hidden. It then passed after the change, checking three seconds before navbar navigation, continued visibility on the next page and dismissal within the remaining budget, preserved grouping, a third incoming update, and no dismissed replay on reload/Back. Closing, acting on or expiring a bar clears its handoff without changing notification read rules.

Updated combined result: **31 tests passed in 83.516 seconds** (26 backend/routing tests and five live-browser tests), using the same disposable file-backed test runner. Django checks, both JavaScript syntax checks and whitespace verification pass. Independent review found no blockers; local served script copies were synchronized. No additional visual styling or backend changes were needed.

## Approved offline delivery follow-up

Eligible unread notifications are now delivered on the next customer login even if they arrived while the user was logged out. `Notification.bar_shown_at` records bar delivery separately from `is_read`. Applied additive migration `0118_notification_bar_shown_at` to the configured local app database; earlier migrations were already applied. Existing unread eligible records receive one delivery because the previous implementation had no persistent display receipts.

The feed remains read-only. A customer-only CSRF-protected POST acknowledges a signed list of precisely the rendered batch's IDs, including arrivals beyond the 20 serialized item bodies. New arrivals after that batch are excluded from its receipt. Acknowledgement is idempotent and never marks a notice read. Browser receipt retries are retained per user across login/navigation and run before another batch is rendered, preventing repeated grouping after a temporary POST failure.

The new backend regression first failed with zero offline updates rather than one; the updated 28-test backend/routing run passed. Additional coverage includes POST-only/CSRF checks, malformed/wrong-owner receipts, admin/guest restrictions, more than 20 arrivals and read independence. The browser flow covers an offline approval at login, no replay on a fresh login with cleared browser storage, grouping two offline updates, failed receipt retries across reload, and a rotated CSRF/session in another tab. The latter initially stalled before the session-change probe was added.

A 403 receipt response now checks the existing session marker before retrying; a changed session reboots the page while preserving the receipt. A modal-scoped observer also resumes polling when a dialog is closed and immediately removed, since its queued close event cannot reach document. This resolved the pending-delivery regression on a reloaded public page's welcome dialog. The observer disconnects after the blocking modal disappears. Independent follow-up review found no blockers in either fix.

Final offline-delivery combined result: **34 tests passed in 73.086 seconds** (28 backend/routing tests and six live-browser tests), using the disposable file-backed SQLite runner. Django system checks, JavaScript syntax checks and migration drift checks pass. Migration 0118 is confirmed applied to the local app database, and the served notification script matches its source. No deployment was performed.

Simultaneous delivery to multiple tabs before a receipt reaches the server is best effort, not transactional exactly-once display. A failed receipt cannot be recovered after all client storage is erased unless the server received it; the corresponding update can be shown again. Closed websites still do not receive browser push notifications. No booking/payment rules or visual styling changed.

## Hover and early-render follow-up

Action text now has no underline at rest and underlines only on hover, without a button background. The close button retains a 44x44 hit target; its visual hover is a subtle 32x32 square instead of the former narrow rectangle. No font sizing or message layout changes.

The navigation delay came from deferred initialization after document parsing. Both client notification scripts now initialize immediately after the complete navbar markup, restoring any valid carried bar before page content is parsed or notification polling finishes. Public navbar routes still perform full document navigation; this is earlier state restoration, not a global single-page navigation rewrite. Account navigation continues to retain its existing shell.

The browser regression failed on the original permanent underline, then on the carried bar being absent during destination-page parsing. It now checks computed action hover/default styles, square close geometry, and an inline parse-time assertion on an actual navbar destination, alongside remaining-time/grouping/dismissal checks. Independent read-only review found no blockers; source and served assets match. Final focused test result: **34 tests passed in 104.044 seconds**, including six live-browser tests. Django checks, JavaScript syntax and whitespace checks pass. No deployment was performed.

## Practical limits

Updates are checked every 15 seconds while the page is visible, plus immediately on focus/return. Native dialog close triggers a check; custom form overlays resume at the next poll. Closed websites do not receive push notifications. Old notices remain accessible through the bell.

This feature's checks do not establish an all-green repository suite. The earlier unrelated full-suite failures and SQLite concurrency errors remain documented in [booking-four-step-verification.md](booking-four-step-verification.md). No deployment was performed.
