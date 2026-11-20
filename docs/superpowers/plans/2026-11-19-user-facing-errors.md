# User-facing Errors Implementation Plan

> **For agentic workers:** Execute the approved scope with independent backend and frontend work, then an independent final review. Track verification below.

**Goal:** Replace the audited technical/vague errors with clear English feedback without changing permissions, payment rules, submission semantics, or validation.

**Architecture:** One small browser error utility distinguishes deliberate user feedback from unexpected exceptions. Screens supply action-specific fallbacks; server endpoints stop returning unexpected exception details. Existing field validation, request status, drafts, abort handling, and retry controls remain intact.

**Tech Stack:** Django, plain JavaScript, Python unittest, Node test runner, Playwright/installed Chrome.

**Spec:** `docs/user-facing-error-message-review.md` and the user-approved message tables in this conversation.

## Global Constraints

- All new user-visible copy is English.
- Preserve the user's existing workspace changes; no deployment or database migration.
- Unexpected results of writes must direct the user to check status before repeating.
- Never expose browser/parser/database exceptions or credentials as UI messages.
- Preserve specific server validation, intentional permission/session messages, and existing statuses.
- Tests use isolated test settings, local storage/email/cache and intercepted network failures.

## Review Focus

- Network failures, malformed JSON, and technical server messages in both inline feedback and popups.
- Successful writes followed by failed refreshes must not be described as failed writes.
- Retry after a lost response must retain drafts/attachments/submission identity.
- Shared helper must load on standalone admin invitation/security pages as well as ordinary pages.
- Normal success, validation, permissions, and double-submit prevention must keep working.

### Task 1: Shared browser feedback and screen integration

- [x] Add failing Node tests for safe messages, unexpected exceptions, technical server responses, and deliberately public validation errors.
- [x] Add `static/js/user_errors.js`, loaded synchronously through existing feedback assets and standalone admin security base.
- [x] Replace raw exception displays with action-specific fallbacks; mark intentional user-facing errors and sanitize server messages.
- [x] Replace audited JavaScript/inline-template copy; refresh local script asset versions.
- [x] Run Node tests and JavaScript syntax checks.

### Task 2: Server copy and safe exception responses

- [x] Add failing Django tests for unexpected design exceptions and API/validation copy.
- [x] Replace audited Python messages, preserve error statuses and validation behavior, and log unexpected design failures privately.
- [x] Ensure AI configuration failures are shown as failures, not successful theme recommendations.
- [x] Run focused server regression suites.

### Task 3: Browser regression and final verification

- [x] Add browser tests using actual Django pages for concern submission/cancellation, design/review actions, and representative admin reads/writes.
- [x] Exercise network loss, malformed JSON, technical server response, validation, retry, and success.
- [x] Run focused browser tests and relevant Django suites; inspect all failures.
- [x] Independently review the task-only changes against the approved scope; resolve substantive findings and rerun affected checks.
- [x] Update verification documentation and report exact results and remaining limitations.

## Progress

- Setup: baseline copies and existing workspace diff saved in `.booking-followup-check/error-copy-implementation/`. Work continues on `fix/user-facing-error-messages`; no existing changes discarded.

- Completion: English replacements implemented; 351 affected-flow tests OK (13 skipped), 34 focused backend tests OK, 9 browser tests OK, and 6 Node entries OK. All 78 JavaScript files and 15 modified inline scripts passed syntax checks. Full-suite baseline limitations and review evidence are recorded in `docs/user-error-message-verification.md`. No deployment, merge, schema migration, or unrelated test-infrastructure fix.
