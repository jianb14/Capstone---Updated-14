# User-facing error message verification

Date: November 19, 2026. Tests use `Project.test_settings`: isolated SQLite, local email/storage, and mocked provider failures. No production data, live payment, or external AI requests were used.

## Backend regression coverage

- Added **21 tests** in `app/test_user_error_messages.py`. They cover private design exception logging, safe action-specific responses, invalid designs, unchanged success/permission/name validation, dynamic retry headers, booking time guidance, offer validation, payment image limits/help, payment cancellation uncertainty, notification parser failures, AI request/image references, configuration failures, and quiz success/error classification.
- Initial red run: **17 tests, 23 expected assertion failures including subtests**. Existing rename and quiz successes already passed. The malformed AI image URL regression was separately observed red with `Invalid IPv6 URL`, then green after safe translation.
- Focused green run: **17 passed**. Broader regression run: **334 tests, OK, 13 skipped**. This covered design save/limits/requirements, offers, service quiz, request protection, AI jobs/text/image saving, GCash/payment administration, booking fee/calendar, notifications, support chat, OTP, and policy email delivery.
- Final follow-up after adding coverage and fixing the malformed image URL: **26 passed, zero skips** (`app.test_user_error_messages` plus the five existing `app.test_ai_image_save` tests).
- Production Python `git diff --check` passed. Existing unrelated `app/apps.py` changes were preserved. No existing tests needed backend wording changes.

Commands:

```powershell
.venv/Scripts/python.exe manage.py test app.test_user_error_messages app.test_ai_image_save --settings=Project.test_settings --noinput

.venv/Scripts/python.exe manage.py test app.test_user_error_messages app.test_design_save app.test_design_limits app.test_design_requirements app.test_offer_editor app.test_services_flow app.test_request_protection app.test_ai_text app.test_ai_image_save app.test_ai_jobs app.test_gcash_qr app.test_admin_payment_workspace app.test_booking_logistics_override app.test_admin_calendar_block app.test_customer_update_bar app.test_customer_notifications app.test_admin_alert_delivery app.test_support_chat app.test_email_otp app.test_policy_notify --settings=Project.test_settings --noinput
```

The broader command's recorded 334-test result predates four additional focused tests; rerunning that command on the final sources discovers more tests.

## Initial full-suite failure investigation

The first full run overlapped implementation: **1,591 tests, 9 failures, 30 errors, 232 skipped**. Its results must not be presented as the frozen-source outcome.

| Initial outcome | Count | Verified classification |
| --- | ---: | --- |
| Account/template `customer_updates.py` syntax errors | 14 errors | Temporary task regression: the first token replacement corrupted two existing regex f-string braces. Both lines were restored before backend regression verification. The current `notification_update` function exactly matches the saved pretask AST. A current 66-test rerun has no syntax errors. |
| Standalone skeleton templates missing `request.session` | 5 errors | Reproduced all five subtest errors using actual saved pretask Python and templates. The RequestFactory fixtures lack session middleware state. `update_session` and `customer_notifications` are unchanged from the saved baseline. |
| Concurrent booking quote/expiry SQLite locks | 2 errors | Both concurrency tests also fail with SQLite lock errors against saved pretask production sources. The contested table can vary with thread timing. `schedule_atomic`, `issue_quote`, and `process_booking` are unchanged from baseline. |
| Design delivery email setup missing `gcash_reference_key` | 9 errors | Current design delivery tests pass independently. The unchanged canvas-label migration test restores the database only to migration 0116, removing payment columns introduced in 0119. Running that migration test followed by a representative design-email test against saved pretask sources reproduces the missing-column error. |
| Dashboard ordering and booking/hero static or layout assertions | 8 failures | Actual saved-baseline execution reproduces all eight failures: dashboard results/operations order; booking picker version, pointer handler, calendar CSS version; edit hint markup, repeated past-date text, edit-field listener; hero CSS version. |
| Map fallback wording assertion | 1 failure | Intentional approved message replacement; the expected old wording needs to follow the new copy. Parent handles this frontend test update. |

Current affected-module rerun:

```powershell
.venv/Scripts/python.exe manage.py test app.test_account_mutations app.test_account_tables app.test_account_workspace app.test_admin_booking_requests app.test_skeleton_loading app.test_design_delivery --settings=Project.test_settings --noinput
```

Result: **66 tests, 5 existing skeleton subtest errors, 3 skipped**. All previously reported account syntax errors are gone; design-delivery tests pass in isolation.

## Reproducible baseline comparison

Local artifacts are under `.booking-followup-check/error-copy-implementation/`:

- `baseline/`: production files saved before this task's implementation.
- `compare_baseline.py`: imports saved production Python, loads saved templates first, and remaps file-reading assertions to saved templates/static files when available. Existing test files and `Project.test_settings` remain in use; active production sources are not swapped or edited.
- `baseline-known-failures.log`: **9 tests; the same 8 failures and 5 skeleton subtest errors**.
- `baseline-concurrency-isolated.log`: **2 tests; 2 SQLite lock errors**.
- `baseline-migration-concurrency.log`: **4 tests; 3 missing-payment-column errors after migration cleanup**, including the representative design-email setup failure.
- `backend-failure-rerun.log`: current-source 66-test result above.
- `django-full-utf8.log`: original full-suite result.

Examples:

```powershell
.venv/Scripts/python.exe .booking-followup-check/error-copy-implementation/compare_baseline.py baseline app.test_skeleton_loading.SkeletonPageCoverageTests.test_standalone_verification_error_and_invitation_templates app.test_admin_dashboard.AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries

.venv/Scripts/python.exe .booking-followup-check/error-copy-implementation/compare_baseline.py baseline app.test_booking_changes.BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule app.test_booking_deadlines.BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification

.venv/Scripts/python.exe .booking-followup-check/error-copy-implementation/compare_baseline.py baseline app.test_canvas_label_cleanup app.test_design_delivery.DesignDeliveryEmailTests.test_blank_message_uses_default_and_username_fallback
```

The final frozen-source full-suite result and browser/Node checks will be recorded below by the parent implementer. No unrelated migration teardown or fixture changes were made during this investigation.

## Final implementation checks

- Final affected-flow regression command: **351 tests, OK, 13 skipped**. This repeats the broader command above and includes `app.test_toast_ui` and `app.test_ai_health`. It includes the additional email-request-limit store failure test (observed red before its copy fix).
- Final focused backend follow-up: **34 tests, OK** (`app.test_user_error_messages`, `app.test_ai_health`, `app.test_ai_image_save`). There are now **22 new backend error tests**.
- Node: **6 test entries passed**: four shared error-feedback tests plus both existing design-rule/upgrade scripts. Unexpected exceptions, technical server responses, deliberate validation, and action-specific fallback copy are covered.
- Final browser run: **9 tests, OK**, with five injected failure variants: aborted connection, malformed JSON, technical JSON error, valid but incomplete JSON, and HTML service error. Actual Django pages cover concern submission/cancellation, committed-but-lost responses and duplicate prevention, design rename/delete, review edit/like, successful review save followed by failed refresh, admin concern reads/writes, successful admin update followed by failed refresh, invitation validation, and preserving the admin booking list when a response is incomplete. Draft text, attachments, submission identity, statuses, normal successful retries, and absence of uncaught page errors are asserted.
- The incomplete admin booking response case was observed red (the list became `undefined`) before adding its guard, then passed in the final browser run. The HTML invitation case also exposed an inaccurate session message; HTML 503 responses now use the uncertain-creation fallback, while actual login/permission responses keep their session instructions.
- Syntax check: **78 JavaScript files and 15 modified inline scripts passed**; all Python modules parse. `git diff --check` passes.
- Exception display scan: remaining `error.message` references are confined to the shared guarded helper and AI health's comparison with an internal marker. No screen directly renders an unexpected exception message.
- Asset versions were refreshed for all edited scripts, and the helper is loaded before consumers on customer, admin, authentication, invitation, and standalone security pages.

Full application recheck: **1,602 tests; 8 failures, 16 errors, 239 skipped**. All remaining failures/errors match the verified pretask groups above: eight old layout/version assertions, five missing-session template fixtures, two SQLite concurrency errors, and nine migration-order schema errors. The temporary syntax regression is absent and the approved map-copy assertion passes. This result is not reported as a clean full suite. Final focused and browser checks above include the subsequent refinements; unrelated test infrastructure was left intact.

The independent review identified generic transport errors overriding write-specific recovery text, a misleading offer “Not saved” status when the outcome was uncertain, and confirmed canvas deletion followed by failed refresh. These were corrected. That reviewer did not deliver a final whole-change verdict after its session became unavailable; the final pass was an author review against preserved pretask sources, including helper load order, permissions, payment sentinel comparisons, drafts, and response parsing. No merge or deployment was performed.

Local logs: `final-regression.log`, `final-focused.log`, `django-final-full.log`, and `browser/browser-final.log` under the implementation artifact directory.
