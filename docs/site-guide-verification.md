# Spotlight tour verification - 12 November 2026

## Current behavior

The user requested a read-only feature tour with Next/Back, a clear focus box, and dimmed surroundings. It replaces the earlier task-aware assistant. Tour steps do not depend on missing answers, validation or transaction progress.

## Complete booking field groups

The schedule target now includes both Start and End, and the venue target includes the address, map and location controls. Design Preferences has separate full-field targets for theme/decor, color palette, motto/backdrop text, special requests and reference pictures in both create and edit forms. Only visible form sections are toured; no form navigation or validation is triggered by the guide.

All **11 guide browser tests passed in 128.472 seconds**. The real-page check verifies both schedule inputs and the map are descendants of their highlighted groups, and opens create/edit Design Preferences in test setup to verify all five explanations are present. Existing border, alignment, hover, keyboard, reduced-motion and cleanup checks also pass. Independent selector review and JavaScript syntax/whitespace checks passed. Log: `.booking-followup-check/site-guide/booking-groups.log`. The complete backend suite was not rerun for this guide-content change.

## Modal-only style correction

The user's intended distinction is a bordered button with a neutral surface outside modals, and borderless ghost styling only inside modals. Restored the page/header/toolbar button treatment while preserving the fixed Guide/X alignment and working hover behavior. Real-page verification now checks the border in both resting and hovered states against the button's actual modal ancestry. This supersedes the page-level ghost treatment mentioned in the earlier alignment fix below.

The expanded real-page check **passed in 77.117 seconds**, covering both themes, desktop/mobile layouts and touch contexts. Border assertions, control-center comparisons and mouse-hover feedback checks all passed. Independent review found no cascade regressions. Log: `.booking-followup-check/site-guide/modal-only-style.log`. No complete backend-suite rerun was needed for this CSS correction.

## Control alignment and ghost-hover fix

- Added actual center-position comparisons for Guide and Close/Done, plus before/after background checks for mouse hover. The previous CSS failed with **26 alignment/hover issues**; viewport-containment checks had not covered these symptoms.
- Corrected the booking form's mismatched control sizes, the payment Close button's negative vertical margin, and modal button alignment. Ghost backgrounds now use a shared CSS variable, so more specific form rules cannot suppress hover. Page-level launchers are also ghost controls; the calendar retains its quiet border and legend alignment.
- **3 focused browser tests passed in 83.246 seconds** after the fix. Coverage includes main feature pages and all supported modal/panel types, booking forms and payment dialogs at 1440/390/320px in both themes, calendar at 768px as well, real coarse-pointer contexts, and native/custom-dialog keyboard behavior. All measured control centers match within 1px, and every mouse-hovered launcher changes its background.
- Inspected final booking-form and payment-dialog screenshots. Independent review found no additional concrete issues. JavaScript syntax, Django system checks and whitespace checks passed. The complete backend suite was not rerun for this CSS correction.

Logs: `.booking-followup-check/site-guide/alignment-hover-before.log` and `alignment-hover-final.log`. Screenshots remain in `.booking-followup-check/site-guide/spotlight/`.

## Compact calendar and borderless modal follow-up

- Calendar Guide now stretches to the legend's height, with smaller text and padding. Real-page browser checks confirm matching height and top position at 1440/768/390/320px in both themes.
- Form and modal Guide launchers use 6px/8px padding, no border and a transparent resting background. Desktop minimum height is 36px; coarse pointers retain 44px. Normal/hover screenshots were inspected across the supported pages, booking/dialog windows and mobile Canvas panels.
- **3 focused browser tests passed in 53.857 seconds**, including the expanded real-page tour check and native/custom-dialog keyboard checks. Independent review found no actionable regressions. Log: `.booking-followup-check/site-guide/compact-borderless.log`. The earlier complete backend suite was not rerun for this CSS-only correction.

## Quiet button and hover correction

- Replaced the high-contrast `currentColor` hover border with muted, theme-specific border and surface colors. Removed the lift and trailing arrow, used a standard help icon, and matched the desktop Canvas launcher's height to Save. Keyboard focus remains visible; coarse pointers retain 44px targets.
- Inspected normal and hovered launchers on real Booking, My Bookings, Canvas, Payments and checkout pages, plus Booking Details, Your Event Design, Edit Booking, Save Design and Payment Details. Mobile Canvas coverage includes Tools, all four inventory categories and the checklist. At 320px, supported dialog headers give their text a full row and place controls beneath it.
- Final focused run: **3 tests passed in 52.788 seconds**, covering the expanded real-page visual tour check and native/custom-dialog keyboard regressions. Empty inventory categories may have only one visible tour step, which the screenshot helper now permits explicitly.
- Independent review found no actionable hover/focus/touch or narrow-header regressions. The booking-change payment route uses the same inspected payment-page template; a separate booking-change transaction was not exercised. No transactions or new backend behavior were added.

Log: `.booking-followup-check/site-guide/quiet-buttons-all-locations.log`. Normal and hover screenshots: `.booking-followup-check/site-guide/spotlight/*-launcher.png` and `*-launcher-hover.png`. The earlier complete backend-suite result below was not rerun for this CSS/template correction.

## Guide button and motion follow-up

- **12 tests passed in 117.983 seconds:** 11 guide checks and the existing account-menu browser regression, after the final header fixes.
- Guide buttons use a consistent focus icon, neutral surface and 44px minimum height. Calendar, booking form, checkout, Canvas Tools, Save Design and payment-details launchers were inspected in real-page screenshots. Calendar coverage includes 1440/768/390/320px and both themes; Canvas also covers 320px. Launchers and tour panels stay inside the viewport, and header controls do not overlap.
- A real booking-form overlap assertion failed before fixing the competing ID-based stylesheet rules. It passes with a reserved control row above the stepper. Canvas Tools keeps the shared Guide style and wraps its header at narrow phone widths.
- Motion regressions cover entry/step animation, rapid Next/Back, close interrupted by account teardown, reopening without stale close callbacks, reduced-motion navigation, and changing the motion preference while closing. The entry-motion assertion failed before the animation implementation.
- Independent review's booking-header finding was reproduced and fixed. Follow-up review reported no additional P1/P2 findings.
- JavaScript syntax, Django system checks and whitespace checks passed. No backend behavior or dependency changed; the complete-suite result below is the earlier run, not a rerun for this visual follow-up.

Logs: `.booking-followup-check/site-guide/polish-browser-final.log`, `polish-header-regression.log`, and `polish-motion.log`. Current launcher and tour screenshots are in `.booking-followup-check/site-guide/spotlight/`.

## Original spotlight browser and visual checks

- **10 tests passed in 79.173 seconds:** 9 spotlight-guide checks plus the existing account-menu browser regression.
- Additional expanded real-page responsive check: **1 test passed in 22.741 seconds**, including desktop/mobile Payments and checkout screenshots.
- The original assistant failed the Next-button contract before replacement. A keyboard-isolation regression also failed before the shortcut fix and passed afterward.
- Pixel inspection confirms that the highlighted region stays bright and surrounding pixels are dimmed.
- Checks cover manual start/no autoplay, Next/Back/Done, prefilled-input preservation, no auto-advance, blocked background clicks/shortcuts, native/custom dialog focus and Escape, skipped/removed targets, viewport/mask alignment and partial account cleanup.
- The actual Fabric canvas retained its object count and selected-object coordinates after Delete, Backspace, arrows, Ctrl+D and Ctrl+Z during the tour. Space still activates the tour Next button.
- Screenshots inspected at 1440, 768, 390 and 320px, with both themes. Application actions were not triggered by tour navigation.
- JavaScript syntax, Django system checks and whitespace checks passed.
- Independent review identified the Canvas shortcut issue; it was reproduced and fixed. Follow-up review found no remaining P1/P2 issues.

## Complete suite and known baseline

The complete Django suite ran **1,511 tests in 442.643 seconds**: **11 failures, 21 errors, 219 skips**. The project-wide suite is not green. The final shortcut/layout refinements were additionally covered by the explicit browser checks above.

An automated Counter comparison confirmed that all 32 failure/error entries, including their multiplicities, match the previously reproduced original-template baseline. There is no new failure/error entry in this complete run. Existing problems concern request fixtures without sessions, stale template/source assertions, booking expectations/SQLite concurrency, and a migration test that leaves the schema at migration 0116 before design-delivery tests. These unrelated application behaviors/tests were preserved.

## Failure/error names

- **ERROR** `app.test_booking_changes.BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule`
- **ERROR** `app.test_booking_deadlines.BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification`
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_attachment_uses_actual_format_and_never_reopens_remote_storage` - 3 entries
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_blank_message_uses_default_and_username_fallback`
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_design_email_has_customer_order_message_and_original_attachment`
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_design_upload_reaches_brevo_as_base64_attachment`
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_email_failure_keeps_design_and_notification_and_reports_problem` - 2 entries
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_email_runs_after_commit_and_replay_does_not_send_twice`
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_missing_customer_email_does_not_lose_design`
- **ERROR** `app.test_design_delivery.DesignDeliveryEmailTests.test_rollback_never_sends_email`
- **ERROR** `app.test_request_protection.RequestLimitsTests.test_limits_are_per_account_and_payment_routes_share_a_budget`
- **ERROR** `app.test_request_protection.RequestLimitsTests.test_oversized_upload_rejected_before_post_is_parsed`
- **ERROR** `app.test_request_protection.RequestLimitsTests.test_upload_bytes_and_request_limits_cover_other_upload_routes`
- **ERROR** `app.test_skeleton_loading.SkeletonPageCoverageTests.test_standalone_verification_error_and_invitation_templates` - 5 entries
- **FAIL** `app.test_admin_dashboard.AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries`
- **FAIL** `app.test_booking_availability.BookingAvailabilityTemplateTests.test_css_cache_bust_updated`
- **FAIL** `app.test_booking_availability.BookingAvailabilityTemplateTests.test_custom_pickers_no_focus_autoopen_and_sturdy_close`
- **FAIL** `app.test_booking_availability.BookingAvailabilityTemplateTests.test_unavailable_calendar_light_gray_and_blocked_icon`
- **FAIL** `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_edit_modal_instant_time_guards_present`
- **FAIL** `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_past_date_validation_in_both_validators`
- **FAIL** `app.test_booking_availability.EditFlowTimeChangeRevalidationTests.test_edit_time_fields_revalidate_on_change`
- **FAIL** `app.test_booking_changes.BookingChangeTests.test_admin_nonrefund_ack_is_shown_only_for_actual_excess`
- **FAIL** `app.test_booking_changes.BookingChangeTests.test_notification_links_go_to_booking_instead_of_review_or_payment_history`
- **FAIL** `app.test_design_delivery.DesignDeliveryEmailTests.test_email_failure_keeps_design_and_notification_and_reports_problem`
- **FAIL** `app.test_hero_stagger.InnerHeroStaggerTests.test_staticfiles_synced_and_cache_busted`

Raw logs: `.booking-followup-check/site-guide/spotlight-browser-final.log`, `spotlight-responsive.log`, and `spotlight-full-suite.log`. Screenshots: `.booking-followup-check/site-guide/spotlight/`.
