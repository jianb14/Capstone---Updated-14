# Category uploads and Theme Decor verification

The implementation adds uploads inside image asset categories, a protected upload-only Theme Decor category, shared catalog/custom placement allowances, persisted personal libraries, and submitted booking reference snapshots. The separate general upload area is replaced by the retained Background controls.

## Verified feature behavior

- 106 focused Django checks passed after the review fixes. These cover upload validation and ownership, transparency and normalization, catalog/custom counts, limits and declared colors, migration conflicts, library persistence, booking snapshots, existing catalog administration, existing Styrofoam Name behavior, large design saves, and GCash QR/storage behavior.
- Seven Node checks passed across `design_rules.test.cjs`, `design_upgrades.test.cjs`, `canvas_category_uploads.test.cjs`, and `user_errors.test.cjs`.
- The dedicated category upload browser check passed in Edge at desktop and phone widths. It verifies upload versus placement counting, mixed catalog/custom allowances, undo/redo, save/reopen, foreign-owner draft rejection, enabled/disabled Theme Decor, excluded-item duplication prevention, mobile Background reopening, image/label separation, and horizontal overflow. Desktop dark and mobile light screenshots were inspected.
- Existing `DesignBrowserTests` and `CanvasInventoryBrowserTests` passed in the same verification sequence. Their obsolete general-upload actions now exercise the retained Background controls; the new category browser test covers the replacement upload flow.
- Django system checks, Python/JavaScript syntax checks, `makemigrations --check --dry-run`, and `git diff --check` passed.

The focused PostgreSQL tests used an explicitly separate `test_balloorina_canvas_review` database. Tests for the final broad run and original-code comparison use their own database names. The original 53-test baseline and the 106 focused checks used the configured password hasher. The final broad run and original-code comparison use a faster password hasher only inside their test processes; production authentication settings are unchanged.

## Applied data changes

Migrations `0122_category_uploads` and `0123_map_theme_decor_inclusions` applied successfully to the configured development database. The existing Theme Decor category keeps ID 25, now with its protected built-in identity and no default catalog images.

The owner explicitly approved mapping the existing Theme Decor rows in Package 1-B, Package 2, Package 3, Package 4, and Stand B. All five now point to category 25, with their existing blank quantities and optional minimum zero. Package 1-A has no Theme Decor rule. A read-only check confirmed that all five package offers remain ready in the designer and that Package 1-A still excludes Theme Decor.

Stand A and Stand B retain their existing disabled designer setting and unresolved non-Theme-Decor setup. The Stand B inclusion mapping is complete; enabling or reconfiguring that existing stand designer was not part of this change.

## Code review corrections

The independent review identified nine important issues. The completed corrections protect existing category data during migration, preserve conflicting inclusion allowances, support nested and live Fabric groups, block excluded custom duplicates, defer library attachment until Save, save canvas/library relationships atomically with row locks, reject explicit foreign-owner browser drafts, retain hidden referenced upload files, and show package mismatch notices for catalog-only submitted layouts. Upload identity checks also agree between the client and server for category, source, and mixed metadata.

Focused regressions cover migration safeguards, grouped counting, nested URL serialization, abandoned upload attachment, saved-library rollback, retained hidden images, package mismatch notices, and client identity validation. The browser check covers the draft-owner and duplicate guards. No review minors were deferred.

## Scope decisions

- Work stays in the user's current checkout and branch. No merge, push, publication, or dependency installation is part of this task.
- Ordinary catalog categories retain their existing active-default-asset readiness requirement. Theme Decor is the explicit exception. Loosening ordinary readiness would change existing behavior.
- Existing anonymous browser draft caches retain their previous compatibility behavior. Newly saved draft caches include an owner and reject a different explicit owner. Unplaced legacy reference-upload caches are not deleted or silently assigned categories.
- Unattached uploads can expire after 24 hours. Images referenced by saved designs or booking snapshots are retained. Browser-only drafts are not permanent storage.
- Image contents, production cost, and physical availability remain subject to the existing administrator review. There is no AI classification, automatic custom pricing, or additional approval workflow.

## Broad regression results

The final fresh broad run completed 1,706 tests in 539.950 seconds: 13 failures, 6 errors, and 233 skips. All 15 unique failing methods match the original-HEAD comparison; the failing-method set difference is empty. The full suite is not green, and its unrelated failures remain outside this task.

The earlier broad run completed 1,700 tests with 13 failures, 8 errors, and 233 skips. It overlapped the review fixes and included two stale-import errors in booking snapshot tests. Those two errors are absent from the fresh final run. The final run is recorded in `category-uploads-final-suite.log`.

The final runner also reported two lingering connections when attempting to drop its isolated temporary database. After the runner exited, cleanup checked the explicitly named test databases for active sessions before removing any unused test database. This did not change the development database.

Fifteen unrelated failing test methods were rerun from an isolated archive of the original HEAD. All fifteen also failed there: 12 failures and 7 errors, including subtest errors. The generated-staticfiles check reports a missing generated file in the clean archive and an outdated expected artifact in the working checkout. The comparison preserves the existing production sources and does not repair unrelated features.

The reproduced methods are:

- `app.test_admin_dashboard.AdminDashboardTests.test_greeting_uses_philippine_time_at_day_period_boundaries`
- `app.test_ai_jobs.AiRequestTests.test_advice_never_spends_image_quota_even_if_model_emits_prompt`
- `app.test_ai_jobs.AiRequestTests.test_empty_package_catalog_is_honest_without_calling_a_provider`
- `app.test_ai_jobs.AiRequestTests.test_mixed_reply_keeps_package_details_when_image_fails`
- `app.test_ai_jobs.AiRequestTests.test_mixed_request_obeys_image_budget_and_still_returns_information`
- `app.test_ai_jobs.AiRequestTests.test_package_question_with_sample_does_not_edit_previous_image`
- `app.test_ai_jobs.AiRequestTests.test_packages_and_sample_use_one_text_reply_and_one_owned_image`
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_css_cache_bust_updated`
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_custom_pickers_no_focus_autoopen_and_sturdy_close`
- `app.test_booking_availability.BookingAvailabilityTemplateTests.test_unavailable_calendar_light_gray_and_blocked_icon`
- `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_edit_modal_instant_time_guards_present`
- `app.test_booking_availability.EditBookingGuardrailTemplateTests.test_past_date_validation_in_both_validators`
- `app.test_booking_availability.EditFlowTimeChangeRevalidationTests.test_edit_time_fields_revalidate_on_change`
- `app.test_hero_stagger.InnerHeroStaggerTests.test_staticfiles_synced_and_cache_busted`
- `app.test_skeleton_loading.SkeletonPageCoverageTests.test_standalone_verification_error_and_invitation_templates`

The skeleton method errors on its five standalone template subcases. These failures are documented rather than changing the unrelated dashboard, AI, booking-calendar, hero, or standalone-auth functionality.

## Temporary verification artifacts

Automatic approval review rejected deletion of the generated original-HEAD baseline folder and ZIP with the reason “blocked by policy.” Those artifacts remain under the already ignored `.booking-followup-check` directory. Source files and unrelated user documentation were not removed.

## Follow-up server startup correction

The reported traceback contained an earlier missing `app_canvasupload` table error and a separate `chat_api` import error. A fresh database inspection confirmed that migrations 0122 and 0123 were already applied and that the upload table existed.

The import error reproduced in an isolated process using the actual runserver initialization branch: a background worker imported `app.views.common` while the main thread loaded `app.urls`. The shared views package had not finished exporting `chat_api`. Ordinary `manage.py check` had passed because it does not start the development workers.

`app/apps.py` now completes URL/view imports on the main thread before starting either background worker. The new `StartupImportTests.test_background_view_import_does_not_break_runserver_urls` reproduced the exact ImportError before the correction and passed afterward. Its worker performs imports only and does not process customer bookings or AI jobs.

All 12 focused startup, background-deadline, and upload checks passed after this correction. Django system and syntax checks passed, and the running local server returned HTTP 200. The earlier full-suite comparison above remains the broad regression record; the full suite was not repeated for this startup-order change.
