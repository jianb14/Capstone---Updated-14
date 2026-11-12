# GCash QR verification — 2026-11-12

## Implemented and exercised

- Normal booking downpayment/full/balance and accepted booking-change top-ups use the same QR/proof screen and saved server-side prices.
- Admin settings support recipient, optional account number, instructions, QR upload and the existing percentage.
- Private proof access, format/size limits, tamper-resistant recipient snapshots, reference uniqueness, duplicate submission, rejection/resubmission, payment deadlines and late-payment handling are covered.
- Payment tracking, receipts, notification behavior, both chatbot knowledge paths, account media deletion, and historical provider returns/webhooks are included in the checked connections.
- Historical session creation/resume is disabled. An unresolved historical session blocks QR collection; its local status link targets the blocking payment.

## Results

| Check | Result | Evidence under `.booking-followup-check/` |
|---|---|---|
| Focused payment/booking/change/admin/privacy/notification/AI suites | 287 tests, OK; 2 PostgreSQL-only skips | `gcash-targeted-verified.log` |
| PostgreSQL payment and concurrency suites | 39 tests, all passed; unique disposable DB destroyed afterward | `gcash-postgresql-verified.log` |
| Browser customer/admin/settings/history flows | 4 tests, all passed | `gcash-browser-verified.log` |
| Responsive customer form | 1440 / 768 / 390 px, light theme; 390 px dark theme; no document overflow; new form text contrast at least 4.5:1 | `gcash-customer-*.png` |
| Merchant confirmation dialog | Approval stays disabled until acknowledgement | `gcash-admin-merchant-check.png` |
| Django checks and migration drift | No issues / no model changes detected | Command results in implementation session |
| JavaScript syntax and whitespace | Passed | `node --check`; `git diff --check` |

The independent reviewer identified four Important issues: reopening reviewed provider payments, mismatched recipient redisplay, private proof cleanup, and targeting the wrong historical checkout. Each was reproduced before its fix. Regression tests also cover legacy whitespace normalization and the old catalog payment guidance.

All final screenshots listed above were opened and inspected. An earlier dark-theme contrast issue was corrected using the existing payment theme variables, and the browser assertion now checks it. One existing admin history browser test failed intermittently during an earlier combined run; it passed on isolated reproduction and in the final combined four-test run.

## Full-suite baseline

The final complete SQLite run executed 1,550 tests: **8 failures, 16 errors, 225 skips**. Every failing test name was already present in the pre-implementation baseline. The remaining groups concern old calendar/template/static-copy assertions, dashboard greeting expectations, synthetic template requests without sessions, design-delivery fixture errors, and two SQLite concurrency checks. The relevant reservation/deadline concurrency checks pass against PostgreSQL in the isolated 39-test run.

The original baseline, before payment implementation, ran 1,516 tests with 34 failures and 148 errors; temporary-file sandbox permission errors account for many of its additional errors. Logs: `gcash-baseline.log` and `gcash-post-review-suite.log`. This change does not claim that the entire repository suite is green.

## Local rollout and limits

Migration 0119 was applied to the verified local PostgreSQL application database after a full `pg_dump` backup and archive validation. No earlier/unrelated migration was applied. Backup: `database-backups/before-gcash-qr-20261112-223929.dump` under the ignored verification directory.

The real merchant QR remains unconfigured. No real transfer, merchant onboarding, hosted deployment, or live Cloudinary authenticated delivery was performed. Cloudinary API behavior is covered by mocked authenticated upload/signed-read checks. Previously public historical proof files, if any, need the operator-controlled privacy migration described in [the rollout guide](gcash-qr-payments.md).
