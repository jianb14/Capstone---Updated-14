# Update bar navigation continuity

> Execute inline using executing-plans. The user approved continuing the existing eight-second timer across navbar navigation.

**Goal:** Carry a visible single/grouped bar to the next page with only its remaining display time.

**Architecture:** Reuse the existing per-user/login session storage namespace. The presenter saves a short-lived snapshot on pagehide, restores it once, and reconciles Back/Forward cache pages. Dismissal clears it. No new dependency, backend or visual changes.

**Spec:** docs/superpowers/specs/2026-11-10-customer-update-bar-design.md

- [x] Add a real-browser regression: three seconds on the first page, navbar navigation, still visible for part of the five remaining seconds, then auto-hide; verify grouped continuation, incoming third update and no dismissed replay on reload/back.
- [x] Observe the missing-continuation failure before changing product code.
- [x] Extend `static/js/customer_update_bar.js` to save/restore validated snapshots and remaining time, without changing existing pause/action behavior. Pass its storage key from `customer_notifications.js`; bump both client/admin shared script versions.
- [x] Run notification backend/browser checks with the documented isolated SQLite browser runner, JavaScript syntax and Django checks. Review the small diff and update verification notes.

Results: regression failed on the original hidden bar after navbar navigation, then passed after implementation (17.780s). Final combined run passed 31 tests in 83.516s, including five live-browser tests. Django checks, both JavaScript syntax checks and whitespace verification passed. Independent read-only review found no blockers. Served local script copies were synchronized.

Ruling: continue in the existing workspace because this follow-up depends on the already authorized, uncommitted feature and must remain available in the user's current local server; no unrelated edits were moved or committed.
