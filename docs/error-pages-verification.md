# Custom error pages: verification

Verified locally on November 10, 2026. UI copy is English and uses the existing Balloorina monochrome branding, local Montserrat font, logo and saved theme preference.

## Behavior

- Production Django handlers return branded 403, 404 and 500 pages with their actual HTTP status.
- Existing direct HTML 403 responses share the design. Existing JSON and AJAX response bodies remain intact.
- CSRF failures show a safe English explanation and retain status 403.
- Generated error responses use JSON when requested explicitly, with `Vary: Accept, X-Requested-With` to separate cached representations.
- Rendering has no request context processors or database dependency. CSS is inline and recovery links work without JavaScript.
- GET/HEAD failures may offer a safe local GET retry link. POST failures never offer to replay the submission.
- Production 404/500 handlers run when `DEBUG=False`; normal Django debug pages remain available with `DEBUG=True`.

## Passing checks

Focused request tests: **13 passed**. These include real exceptions, unknown routes, direct forbidden responses, CSRF, JSON/AJAX preservation, response headers/cookies, HEAD behavior, context processor/database independence, safe retry URLs and cache variation.

Arrow refinement: replaced the font-dependent arrow glyph with an aligned 18px SVG icon. Re-ran all 13 request tests and both browser tests: **15 passed**. Desktop/mobile screenshots and exported HTML previews were refreshed.

Final regression run: **137 tests, 132 passed, 5 optional tests skipped**. It included error pages, real browser tests, admin security and modal routes, support chat, request protection, account deletion and account mutations.

```powershell
$env:RUN_ERROR_PAGES_BROWSER='1'
./.venv/Scripts/python.exe manage.py test app.test_error_pages app.test_error_pages_browser app.test_admin_security app.test_admin_modal_routes app.test_support_chat app.test_request_protection app.test_account_deletion app.test_account_mutations --settings=Project.test_settings --noinput
./.venv/Scripts/python.exe manage.py check --settings=Project.test_settings
git diff --check
```

Chrome checks covered 403/404/500 in dark and light themes at 1440×900, 1024×768, 768×1024, 390×844, 320×568 and 640×360. Verified readable text contrast, no horizontal overflow, keyboard focus, local asset loading, working home/login/services/retry links, and usability with scripts disabled and static assets blocked. Screenshots are in `.booking-followup-check/error-pages/` (ignored local artifacts).

The design inspector reported **0 failures**. Three warnings concern the intentionally prominent error number/title and the small HTTP label; this is a standalone error screen rather than a dashboard.

An independent code review checked the final changes and reported no remaining substantive findings. Retry URL and cache-header findings were covered by tests observed failing before their fixes.

## Full-suite limitations

```powershell
./.venv/Scripts/python.exe manage.py test --settings=Project.test_settings --noinput
```

This run discovered **1,475 tests: 13 failures, 2 errors, 203 skipped**. Both errors are SQLite table-lock errors in concurrent booking tests. The failures concern existing dashboard markup, booking templates, notification routing, cache-version expectations and stale ignored staticfiles mirrors.

To distinguish these from the new feature, all 15 failing tests were replayed with `app.error_pages.ErrorPageMiddleware` disabled, the three custom URLconf handlers removed and the original Django CSRF failure view restored **in a separate process only**. The replay produced the exact same 13 failures and 2 errors, with matching test identifiers. The new error-page tests and final regression run pass. The full suite is therefore **not green**, and those unrelated tests were left unchanged.

Failures:

- `app.test_admin_dashboard.AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries`
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_css_cache_bust_updated`
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_custom_pickers_no_focus_autoopen_and_sturdy_close`
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_unavailable_calendar_light_gray_and_blocked_icon`
- `app.test_booking_availability.BookingMapModuleScopeTests.test_static_and_staticfiles_mirrors_in_sync`
- `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_edit_modal_instant_time_guards_present`
- `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_past_date_validation_in_both_validators`
- `app.test_booking_availability.EditFlowTimeChangeRevalidationTests.test_edit_time_fields_revalidate_on_change`
- `app.test_booking_changes.BookingChangeTests.test_admin_nonrefund_ack_is_shown_only_for_actual_excess`
- `app.test_booking_changes.BookingChangeTests.test_notification_links_go_to_booking_instead_of_review_or_payment_history`
- `app.test_booking_design_step.BookingDesignStepTemplateTests.test_map_module_and_css_files_exist`
- `app.test_booking_view_map.BookingViewMapMarkupTests.test_staticfiles_mirrors_in_sync`
- `app.test_hero_stagger.InnerHeroStaggerTests.test_staticfiles_synced_and_cache_busted`

SQLite concurrency errors:

- `app.test_booking_changes.BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule`
- `app.test_booking_deadlines.BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification`

Local test logs are in `.booking-followup-check/error-pages-*.log`. Verification uses isolated SQLite test databases, not production data. No deployment was performed; hosting-provider error pages outside Django are outside this change.
