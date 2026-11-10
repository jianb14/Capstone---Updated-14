# Four-step booking verification — 2026-11-10

Historical verification for the original inline version. The user subsequently approved replacing inline samples with an on-demand gallery inside the same modal; see [the gallery design](superpowers/specs/2026-11-10-booking-package-gallery-design.md). The full-suite baseline failures recorded below remain relevant.

The create and edit forms now use Event Details → Select Package → Design Preferences → Review & Confirm. Package samples expand inline. Repeating a selected package click or using Hide preview collapses images while retaining selection. Remove package clears the base selection so customers can choose a solo entrance arch. Existing extras, pricing, availability, uploads and saved-design handling remain in their existing code paths.

Shared CSS/JS URLs use `20261110fourstep` to avoid reusing incompatible cached assets.

## Browser verification

The focused Django run passes all 113 tests in preview, design-step, form-parity, package-catalog, step3, customer-modal and design-requirement suites (21.896 seconds).

Passed seven tests across `app.test_booking_four_step_browser`, `app.test_booking_package_catalog_browser` and `app.test_booking_change_feedback_browser` (206.350 seconds). Passed `app.test_services_browser` separately (81.378 seconds).

Coverage includes desktop/mobile light and dark modes, four indicators, first-step validation, keyboard selection, expanding/collapsing without deselection, switching packages, extras, empty/broken images, clearing the package and choosing a solo arch, back/next persistence, review totals, saved-design create/edit, paid change-request cancellation, catalog ordering, and service/login continuation. Screenshots are in `.booking-followup-check/four-step/`.

`node --check static/js/booking_form_ui.js` and `git diff --check` pass. UI style lint reports zero failures; its four shadow warnings refer to existing rules.

## Full repository suite

Ran `python manage.py test --settings=Project.test_settings --noinput`: 1,492 tests, 208 skipped, 11 failures and two errors (506.672 seconds). This is not an all-green repository result.

Six availability source assertions also fail against HEAD templates before the four-step changes. Verified by reading the HEAD template content in memory while running those same assertions, without replacing workspace files:

- `BookingAvailabilityTemplateTests.test_css_cache_bust_updated`
- `BookingAvailabilityTemplateTests.test_custom_pickers_no_focus_autoopen_and_sturdy_close`
- `BookingAvailabilityTemplateTests.test_unavailable_calendar_light_gray_and_blocked_icon`
- `EditBookingGuardrailTemplateTests.test_edit_modal_instant_time_guards_present`
- `EditBookingGuardrailTemplateTests.test_past_date_validation_in_both_validators`
- `EditFlowTimeChangeRevalidationTests.test_edit_time_fields_revalidate_on_change`

Other failures in the full run concern code outside the four-step implementation; a full baseline run was not performed for these:

- `AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries` — dashboard section order assertion.
- `BookingChangeTests.test_admin_nonrefund_ack_is_shown_only_for_actual_excess` — expected admin excess-payment wording.
- `BookingChangeTests.test_notification_links_go_to_booking_instead_of_review_or_payment_history` — notification URL expectation.
- `EmailOTPTests.test_wrong_attempt_limit_survives_new_session_ip_and_resend` — expected 200, received 302.
- `InnerHeroStaggerTests.test_staticfiles_synced_and_cache_busted` — old base.css cache-version expectation.

The two errors are SQLite table locks in `BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule` and `BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification`.

Logs: `.booking-followup-check/four-step-full-suite.log`, `four-step-baseline-availability.log`, `four-step-browser-final.log`, and `four-step-services-browser-verified.log`.

No deployment was performed. External map providers were blocked in the focused browser tests; the service continuation test also exercised the existing map-ready pin validation.
