# Booking status emails verification (2026-11-19)

## Final focused regression run

158 tests passed (54.792 seconds), including all 17 new customer status email tests:

```powershell
.venv/Scripts/python.exe manage.py test app.test_booking_status_email app.test_booking_deadlines.BookingDeadlineTests app.test_booking_changes.BookingChangeTests app.test_email_delivery app.test_design_delivery app.test_admin_booking_workspace app.test_admin_payment_workspace --settings=Project.test_settings --noinput
```

Log: `.booking-followup-check/booking-status-email-final-focused.log`.
Uses isolated SQLite and in-memory email; no real customer emails sent.
`manage.py check`, `makemigrations --check --dry-run` with `Project.test_settings`,
and `git diff --check` pass. No migration is needed.

The new tests first failed with email handling absent. Actual submission testing
then caught string event times retained in newly created model instances; the
handler now reads persisted field values before capturing its email content.
Reviewer caught localhost entries selected before public addresses; two regression
tests failed before fixing hostname/loopback filtering, then passed in the final run.
Final independent review reports no remaining findings.

## SQLite concurrency limits

The initial related suite hit these errors:

- `app.test_booking_deadlines.BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification`
- `app.test_booking_changes.BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule`

Both reproduce with the new email receiver disconnected: SQLite reports database
table locking. Baseline reproduction and output are in
`.booking-followup-check/booking_status_email_concurrency_baseline.py` and
`.booking-followup-check/booking-status-email-concurrency-baseline.log`.
Real row-lock concurrency requires isolated PostgreSQL verification.

## Deployment

Deploy the code and use a valid existing Brevo configuration. Public customer links
use `BOOKING_EMAIL_BASE_URL` or the documented domain fallbacks. Actual provider
acceptance/inbox delivery was not tested against the live deployment.

## Whole-project run

The initial full-suite process (started before the submission and assertion-context
fixes) completed 1,568 tests in 398.955 seconds: 10 failures, 16 errors, 228 skips.
It is **not a passing full-suite result**. Full output:
`.booking-followup-check/booking-status-email-full-suite.log`.

Two failures in that initial snapshot were the new submission email and deferred
warning-assertion tests. Both were corrected and pass in the final 158-test run.
Other failures/errors were outside this change's edited code:

- `app.test_skeleton_loading.SkeletonPageCoverageTests.test_standalone_verification_error_and_invitation_templates`:
  five template subcases fail because the test request lacks `session`.
- The two concurrency tests named above fail on SQLite locking, also reproduced
  with the email receiver disconnected.
- `app.test_design_delivery.DesignDeliveryEmailTests`: nine errors because the
  full-suite test database lacks the payment column `gcash_reference_key`.
  All nine pass in the final focused run. Affected tests:
  `test_attachment_uses_actual_format_and_never_reopens_remote_storage`,
  `test_blank_message_uses_default_and_username_fallback`,
  `test_design_email_has_customer_order_message_and_original_attachment`,
  `test_design_upload_reaches_brevo_as_base64_attachment`,
  `test_email_failure_keeps_design_and_notification_and_reports_problem`,
  `test_email_runs_after_commit_and_replay_does_not_send_twice`,
  `test_invalid_unpaid_or_unauthorized_uploads_never_send_email`,
  `test_missing_customer_email_does_not_lose_design`, `test_rollback_never_sends_email`.
- `app.test_admin_dashboard.AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries`:
  an assertion on dashboard section order fails.
- `app.test_booking_availability.BookingAvailabilityTemplateTests`:
  `test_css_cache_bust_updated`, `test_custom_pickers_no_focus_autoopen_and_sturdy_close`,
  `test_unavailable_calendar_light_gray_and_blocked_icon` fail template assertions.
- `app.test_booking_availability.EditBookingGuardrailTemplateTests`:
  `test_edit_modal_instant_time_guards_present`, `test_past_date_validation_in_both_validators`
  fail template assertions.
- `app.test_booking_availability.EditFlowTimeChangeRevalidationTests.test_edit_time_fields_revalidate_on_change`
  fails a template assertion.
- `app.test_hero_stagger.InnerHeroStaggerTests.test_staticfiles_synced_and_cache_busted`
  fails a template/cache-version assertion.

No unrelated template, concurrency, or migration-test changes were made.
