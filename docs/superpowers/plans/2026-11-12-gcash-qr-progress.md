# Execution ledger — plan: docs/superpowers/plans/2026-11-12-gcash-qr.md

- Approval: user accepted the proposed QR/manual verification flow and instructed implementation across all connected features.
- Workspace: preserve current uncommitted site-guide/manual work. Work in the user-specified workspace; do not create a second checkout or change branch under unrelated edits.
- Pre-flight: all tasks share Payment/GCashProofForm; task 1 defines those interfaces before submission/UI and guidance changes.
- Baseline: 1,516 tests; 34 failures / 148 errors / 224 skips. Windows sandbox denied temporary-file access; repeated checks used approved local test access. Preserve the original log at .booking-followup-check/gcash-baseline.log.
- Task 1: complete. Shared form validation, additive fields/migration, private proof storage, recipient settings and QR upload. Initial 18 new tests passed after expected RED failures.
- Task 2: complete. Initial/full/balance/change flows, protected proof viewer and QR download, payment tracking, merchant approval acknowledgement, rejection/resubmission, and historical provider recovery.
- Task 3: complete. Chatbot and guide wiring updated. Independent review returned four Important findings, all reproduced and fixed with regression tests; no Critical finding was identified.
- Final verification: 287-test focused suite OK (2 PostgreSQL-only skips); 39/39 PostgreSQL tests OK in a unique disposable database, including those concurrent reservation/deadline/checkout tests; 4/4 browser tests OK. Django checks, migration drift check, JavaScript syntax and git diff whitespace check passed.
- Full suite after review: 1,550 tests, 8 failures / 16 errors / 225 skips. Every failing test name was also present in the original baseline; see docs/gcash-qr-verification.md for scope and causes.
- Ruling: preserve nullable legacy reference keys instead of destructive deduplication/backfill — historical payments may already share references; legacy active references are normalized and checked before new submission. Cost: the remaining legacy reference scan grows with historical data.
- Ruling: permit the additive migration only after verifying the actual PostgreSQL server is loopback/local and validating a full backup — keeps the running local application compatible with its model changes. Applied only 0119; no hosted database or financial records changed.
- Backup: .booking-followup-check/database-backups/before-gcash-qr-20261112-223929.dump (validated with pg_restore --list).
- Rollout boundary: no actual merchant QR was supplied/configured, no real financial transfer performed, no publishing or third-party contact. New collections remain unavailable until a real recipient and QR are configured.
