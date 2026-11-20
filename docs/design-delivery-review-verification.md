# Missed design delivery: verification

Implemented November 20, 2026. Migration `app.0121_design_delivery_review` is applied to the configured **local PostgreSQL** database. Existing record counts remained **54 bookings / 31 payments** before and after the migration.

## Available flow

Admin → Bookings → Design Delivery → **Needs admin review** → **Review issue** → **Record design resolution**.

- A confirmed booking without its current design becomes overdue at the saved deadline and needs review at its actual event end, including overnight events and legacy schedules.
- Late uploads retain their original deadline and upload time and do not close a missed-delivery review.
- External delivery, late online delivery, or an agreed customer resolution records notes, actual delivery time where applicable, admin, resolution time, and service fulfillment.
- Completion requires an ended event and a resolved design issue with fulfilled service. Cancellation and payment rules remain separate.
- Deleted supporting images reopen an active review; the customer retains resolution history. The last image supporting an already completed online resolution cannot be removed.
- Current review ID/version and design revision reject stale or conflicting submissions. Identical retries do not repeat history or notifications.
- Legacy images without a stored deadline have unknown timeliness; changing the booking date cannot rewrite known delivery timing.

## Passed checks

| Check | Result |
|---|---|
| Booking, design, customer modal, and change-request regression suites | **241 tests passed** |
| Isolated PostgreSQL database: feature, admin workspace, all deadline tests, and concurrent change quotes | **76 tests passed**, including both concurrency cases that SQLite cannot serialize |
| New feature tests | **38 passed** on SQLite and PostgreSQL |
| Design review browser flow | Passed: validation, resolution save, customer explanation, 1440/390/320px layouts, light/dark screenshots |
| Existing booking workspace browser suite plus new browser test | 5 passed; 1 pre-existing error-copy assertion failed (see below) |
| Django system checks | No issues |
| Migration consistency | No changes detected |
| JavaScript syntax and `git diff --check` | Passed |

SQLite regressions use `--settings=Project.test_settings`; PostgreSQL verification creates and destroys a uniquely named disposable database and never uses the application database as a test database. Browser screenshots and raw logs are in `.booking-followup-check/design-review/`.

## Full-suite result and existing failures

The final full isolated SQLite run executed **1,688 tests** in **472.465 seconds**: **8 failures, 7 errors, 260 skipped**. All remaining failures/errors below were reproduced against an unchanged snapshot of `f676d0757eca3be04971385f8705fc79eb17fba1`. They were not changed as part of the design-delivery feature.

Failures:

- `app.test_admin_dashboard.AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries`: existing dashboard element-order expectation.
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_css_cache_bust_updated`: existing cache-version assertion.
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_custom_pickers_no_focus_autoopen_and_sturdy_close`: existing source-text assertion.
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_unavailable_calendar_light_gray_and_blocked_icon`: existing calendar cache-version assertion.
- `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_edit_modal_instant_time_guards_present`: existing markup assertion.
- `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_past_date_validation_in_both_validators`: existing validation-text assertion.
- `app.test_booking_availability.EditFlowTimeChangeRevalidationTests.test_edit_time_fields_revalidate_on_change`: existing source-text assertion.
- `app.test_hero_stagger.InnerHeroStaggerTests.test_staticfiles_synced_and_cache_busted`: existing base CSS cache-version assertion. The baseline snapshot used the same collected base CSS file as the working checkout.

Errors:

- `app.test_skeleton_loading.SkeletonPageCoverageTests.test_standalone_verification_error_and_invitation_templates`: five subtests (`verify_otp`, `verify_email_link`, `change_signup_email`, `errors/request_limit.html`, `admin/security/accept_invitation.html`) construct a request without a session, while the existing customer-updates context processor requires one.
- `app.test_booking_changes.BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule`: SQLite table lock; **passed on PostgreSQL**.
- `app.test_booking_deadlines.BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification`: SQLite table lock; **passed on PostgreSQL**.

Separate existing browser failure:

- `app.test_admin_booking_workspace_browser.AdminBookingWorkspaceBrowserTests.test_modal_errors_distinguish_server_records_permissions_and_login_then_retry`: expects “The server could not load this information.” while the unchanged implementation returns “We couldn't load this booking. Please try again.” Reproduced against the original snapshot.

## Review

A fresh read-only reviewer identified seven correctness issues. Regression tests were observed failing before fixes, then passed: completed-image protection, conflicting/stale resolution submissions, retained customer history, event-ended messages, deadline snapshots, pre-upgrade customer notices, and unpaid legacy review visibility. No review findings were deferred. This report covers the local app and isolated test databases.

The review-queue notice also uses the existing light/dark theme colors, a responsive action button, and the user's selected subtle hover style. Browser checks covered contrast, keyboard focus, queue navigation, and 1440/390/320px layouts in both themes.
