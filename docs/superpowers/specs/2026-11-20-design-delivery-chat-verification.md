# Design delivery chat verification

## Implemented behavior

- A successful admin design send creates one linked card in the customer's Admin Support conversation, creating or reopening that conversation as needed.
- The card has the booking number, standard greeting, optional existing admin message, full-image preview, and an authorized booking link. Revised designs use the updated-design label.
- Existing submission receipts prevent duplicate cards/emails; delivery and chat save in one transaction. The existing design email is retained without adding offline-chat email.
- Deleting the delivery removes its image from the card, replies, pinned previews, inbox preview, shared photos, and an already-open image dialog. Removed cards remain readable.
- Delivery text cannot be altered through either chat edit endpoint. Unrelated ordinary messages retain their existing actions.
- Migration `app.0120_chat_design_delivery` has been applied to the configured local PostgreSQL database.

## Verification evidence

- Original targeted baseline: 53 tests passed.
- Final backend regression: 77 tests, OK, one SQLite skip. Includes design delivery/email, support chat, admin booking workspace, booking design concurrency, and migration-fixture cleanup.
- PostgreSQL concurrency: two tests passed in a uniquely named temporary database. Both lock orderings first reproduced actual PostgreSQL deadlocks before the fixes, then passed using user row locks that permit foreign-key checks.
- Browser regressions: initial feature/reviewer regression run passed three tests covering both chat surfaces, uploaded images, customer feedback, revisions, removal while dialogs are open, hostile caption text, and 1440/390/320 light/dark layouts. The final isolated two-test feature browser run passed; see `.booking-followup-check/design-chat-final-feature-browser.log`. After compacting the greeting and preview, the final combined design/email/browser run passed all 22 tests; see `.booking-followup-check/design-chat-final-polish.log`. Screenshots were inspected after that run.
- Django system checks, migration drift check, JavaScript syntax check, and `git diff --check` passed.
- Screenshots: `.booking-followup-check/design-delivery-chat/`.

## Follow-up: light-mode labels and immutable chat delivery cards

- Reproduced the admin light-theme issue with the actual stylesheet order: global heading and paragraph overrides made the title/booking ID dark against the outgoing dark bubble. Delivery labels now inherit the bubble text color with sufficient priority. The real-browser regression checks the title, booking ID and booking link against the visible message color in both themes and both chat surfaces.
- Removed the Delete action from delivery-card menus. Both support and legacy chat deletion endpoints reject active and removed delivery cards without changing their pinned state or history. Ordinary chat message actions remain covered by the support suite.
- Verified RED then GREEN for stylesheet contrast and both deletion endpoints. Final run: 67 design delivery, support chat and browser tests passed in `.booking-followup-check/design-chat-contrast-delete-green.log`. The admin light-mode screenshot was inspected after the run.

## Existing repository test issues

The broad run discovered 1,639 tests and ended with eight failures, 25 errors, and 252 skips. It was run before the final review fixes. A separate checkout of the original HEAD reproduced all eight assertion failures listed below, the missing-session template errors, migration-fixture contamination, and SQLite concurrency errors. The original-source checkout also lacks some collected-static fixtures, so its overall counts are not directly comparable.

| Module | Existing failing assertion |
| --- | --- |
| `app.test_admin_dashboard` | `test_greeting_uses_philippine_time_at_day_period_boundaries` |
| `app.test_booking_availability` | `test_css_cache_bust_updated` |
| `app.test_booking_availability` | `test_custom_pickers_no_focus_autoopen_and_sturdy_close` |
| `app.test_booking_availability` | `test_unavailable_calendar_light_gray_and_blocked_icon` |
| `app.test_booking_availability` | `test_edit_modal_instant_time_guards_present` |
| `app.test_booking_availability` | `test_past_date_validation_in_both_validators` |
| `app.test_booking_availability` | `test_edit_time_fields_revalidate_on_change` |
| `app.test_hero_stagger` | `test_staticfiles_synced_and_cache_busted` |

Other broad-run errors:

- `app.test_skeleton_loading.SkeletonPageCoverageTests.test_standalone_verification_error_and_invitation_templates`: five template subtests construct a request without a session.
- `app.test_booking_changes.BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule`: SQLite table lock in the existing scheduling concurrency fixture.
- `app.test_booking_deadlines.BackgroundDeadlineTests.test_concurrent_checks_create_one_expiration_notification`: SQLite table lock in the existing deadline concurrency fixture.
- The existing canvas-label migration test restored migration 0116 instead of the current schema, causing 18 subsequent design/email test setup errors due to the missing GCash payment column. Its cleanup now restores migration graph leaves. The final targeted run includes that migration test followed by delivery/email tests and passes.

The additional seven-test shared-chat browser run passed five tests and failed two: the new delivery test was checked in a background tab before its initial fetch completed, and the existing `test_async_inbox_thread_drafts_reply_retry_search_and_customer_updates` expects the old text “Could not connect” instead of the current retry error. The delivery test now activates the inspected tab and permits the normal asynchronous load; final feature results are in the isolated browser log above. The old exact-copy assertion is unchanged.

## Review decisions

- Kept the existing conversation and styling; no dependency or separate messaging pipeline was added.
- No historical delivery backfill, new approval workflow, or extra chat email.
- Preserved unrelated workspace files and kept the implementation on the existing feature branch.
- The full repository suite is not claimed to be green; unrelated failures above remain outside this feature.
- Automatic approval review rejected recursive cleanup of the temporary baseline archive/extraction. Those artifacts remain under the ignored `.booking-followup-check` folder; application files and the local migration are unaffected.
