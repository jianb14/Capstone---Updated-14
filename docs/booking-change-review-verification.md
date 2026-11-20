# Request Changes review verification

Verified locally on November 20, 2026, against the approved request-review and payment-breakdown design.

## Result

- Review & Confirm retains the full Booking Details and Booking Summary cards and marks changed, added, and removed values. Reference pictures show retained/added/removed status; non-removable saved custom-design thumbnails remain visible.
- The original baseline and request-mode prefill come from the owner-checked endpoint. Booking/reference/design changes invalidate the version and require reopening the draft. Moving backward or reverting values compares against the original reservation, and a no-change draft cannot be submitted through the review.
- Review uses the existing server proposal calculation, saved prices, fee policies, and shared Decimal payment arithmetic. Missing historical unit prices are identified as unavailable without inventing prices or item switches.
- Compact payment rows inside Booking Summary show verified credits and the estimated remaining balance. One short conditional note explains the change top-up/later booking balance when applicable. Unpaid bookings retain the full estimated booking balance and existing payment terms. A lower total with actual estimated excess retains the existing policy explanation and acknowledgment.
- An overpaid original booking receives a team-review explanation when the existing policy's change top-up would exceed its estimated outstanding balance; the UI does not falsely describe those amounts as components of one another. Existing payment policy is unchanged.
- A read-only preview POST on the existing change endpoint rechecks eligibility and current payments before showing amounts. Preview uploads only the reference-picture count; actual files are sent on submission. Failed/blocked previews hide stale amounts, disable submit, and provide retry. Fresh excess-payment confirmation occurs after the authoritative payment refresh.
- Previews have a separate 30-per-minute rate budget and do not consume the booking-change submission quota. Existing authentication, ownership, submission validation, and actual request processing remain in force.
- Closing/reopening clears comparison/upload-preview state. Normal pending edits and new-booking review retain their existing behavior.

The user's subsequent visual correction restores the original row-info/row-label/row-value markup, icons, fees, and Total Price display. Changes use a small soft badge and muted Previously annotation without borders or shaded callouts. Booking Summary contains requested items only; removed items are not duplicated there. Changed requested items and fees have a Changed badge beside their label, and changed fees show their previous amount. Payment information has no separate heading or panel. Current total and its value share one line, with the estimated increase/decrease beneath. Reference pictures are grouped by status with badges beside the field label.

## Verification

### Visual refinement

Disabled submit styling: unchanged review drafts now display a muted button at 60% opacity with a not-allowed cursor and no active hover effects. The enabled style returns after reviewing actual changes. The focused browser test passed in light and dark themes, checking disabled/hover appearance, enabled restoration, both no-change messages, and confirmed request submission. Log: `.booking-followup-check/request-step-toast/disabled-style.log`.

Final clarification: the inline no-change message is restored above the submit buttons, in muted gray without an icon, alongside the existing top-right toast. It hides when the draft changes or resets. The focused browser test passed, checking both messages, absence of inline icons, disabled unchanged submission, note removal after editing, and successful confirmed submission. Log: `.booking-followup-check/request-step-toast/note-restored.log`.

Latest user correction: the request/reason banner now replays its entrance on every Next/Back step transition, including initial modal opening. The no-change inline note has been removed; the existing top-right info toast displays the full guidance as one message, and submission remains disabled. Request-only timing and reduced-motion support remain intact. The final two browser tests passed: initial/repeated step entrance across all four steps and reduced motion; no-change toast/no inline note, followed by edits and successful confirmed submission. All 37 focused regression tests passed. Logs: `.booking-followup-check/request-step-toast/`.

No-change guidance now appears immediately above the Back/Submit actions as muted-gray text with an info icon. The top status remains reserved for preview loading/errors and Retry. The bottom note disappears on editing, mode changes, and reset. Request-mode banner uses the existing fadeInUp entrance at 400ms; form content follows with a 140ms stagger. Reopening restarts the entrance and reduced-motion disables it. Pending-edit motion remains unchanged.

Verification: 37 focused regression tests passed. Eight browser tests in the combined run passed, including banner timing/reduced motion, status colors, field focus, pending edits, request/confirmation saves, custom designs, and maps. The remaining placement test initially inspected the static note before its asynchronous preview made it visible; after waiting for visibility, its rerun passed, confirming proximity to submit actions, gray color, info icon, and disappearance after editing. All 9 browser checks passed across these final runs. Independent review found no substantive issues. Logs: `.booking-followup-check/request-review-motion/`.

Submission confirmation update: all three dialogs use the user's exact approved title, message, and buttons. Pending edits and change requests ask only after review/validation, before the POST. Review Again retains the draft without saving. A per-form guard prevents duplicate confirmations; a changed draft, invalidated preview, stale page, or different booking action cannot be submitted after the dialog resolves. Existing direct-update and change-request endpoints are unchanged. New-booking wording uses Submit your booking request? and Submit Request as approved. Logs: `.booking-followup-check/booking-confirmations/`.

Confirmation verification passed 37 focused server tests and 7 browser tests. After the final changed-draft safeguard, the request-change invalidation/save test and the new-booking/pending-edit confirmation tests were rerun: all 3 passed. They verify exact copy, Review Again cancellation, direct pending/custom-design saves, request submission, and rejection of a draft changed during confirmation. Independent final review found no substantive issues. JavaScript syntax and whitespace checks passed. These are local focused checks; no deployment was performed.

Map/focus/status correction: review now uses one Map Pin label with the current map and a change badge. The separate textual pin comparison and Venue Map label are gone. Event Details validation, invalid time paths, and Design Preferences use the shared visible-control focus helper with preventScroll followed by centered smooth scrolling (instant for reduced-motion preferences). Editable map messages use explicit error/loading/success states, with scoped theme colors that override the old global gray small-text rule. Direct required-pin validation also assigns the error state.

The final combined run passed **47 tests, including 10 browser tests**, across create, edit, and request-change flows. Two dedicated browser tests verify event/time field focus, design theme/palette group focus, smooth/reduced-motion scroll options, and distinct required/loading/pinned colors in both themes. The run also covers saved comparisons, custom designs, actual venue markers, direct saves, and existing responsive navigation. Eight additional existing map regression tests passed. The map lifecycle script's local collected copy was synchronized. Independent review found no remaining substantive issues. Logs: `.booking-followup-check/map-focus-polish/`.

Pending-edit comparison extension: **45 tests passed, including 8 browser tests**. Direct pending edits now use a fresh owner-checked, no-store baseline from the existing edit endpoint and show the same detail/item/fee/image annotations. Direct Update Booking remains in place, with no reason prompt, quote/payment-request panel, or BookingChangeRequest. Browser checks directly saved both catalog and custom-design pending bookings, verified Changed/Added/Previously rendering, and held an older baseline response while opening another booking to verify it could not overwrite the newer form. Custom designs without catalog cards retain their saved base amount. Existing create navigation, request changes, payment states, overtime styling, and venue maps were regression-checked. Independent final review reported no substantive issues. Logs: `.booking-followup-check/pending-review/`.

Latest badge/overtime polish: new requested items show Added without Previously: None; replaced items retain Changed and their saved predecessor. The shared overtime note uses a neutral surface, clock icon, started-hour calculation, and right-aligned fee across create/edit/request. Duplicate rate wording is removed only while the fee note is visible; start-only/no-overtime hints still disclose the rate before selection. Existing confirmation and pricing logic remain intact. Seven browser tests passed, including overtime screenshots in all three modes at desktop/light and mobile/dark. The independent reviewer found no substantive regressions. Logs are in `.booking-followup-check/overtime-polish/`.

The broader availability run exposed six pre-existing source-string assertions (cache versions, picker event wiring, old date-hint markup, date-validation structure, and old time listener structure). A read-only comparison against the preserved baseline reproduced the same six failures. Two hint-rate assertions exposed by shortening the text were restored by retaining rate disclosure when no overtime fee note is visible. See `baseline-comparison.log` for the exact failure identifiers; the final focused run excludes only the six baseline failures and passed all 94 remaining tests.

The follow-up Previous-item annotation passed **5 request-review browser tests**. Changed requested packages/extras show their saved predecessor's name and amount beneath the label; replacements match the same item role, newly added extras show Previously: None, unknown historical unit prices remain unavailable, and reverting extras removes the annotation. Requested rows remain the only price-bearing item rows. The browser run also rechecked payment states, preview retry, real pinned maps, custom designs, and normal edits. Logs are in `.booking-followup-check/review-previous-items/`.

The subsequent annotation/map correction passed **58 regression tests and 8 browser tests**. Tests verify Changed badges on requested packages and changed logistics/overtime, aligned current-total figures with the delta below, reference-picture badges in field headers, and actual Leaflet markers in Step 4 for new bookings, direct edits, and change requests. Re-entering review updates the marker to the latest submitted coordinates; missing coordinates remove the old map. Tests use the application's Leaflet 1.9.4 (cached from the existing CDN) and deterministic image tiles; production continues using the existing map provider. A separate live provider check returned a valid HTTP 200, 256×256 tile. Light/dark screenshots at 1440px and 390px were inspected. Logs and map screenshots are in `.booking-followup-check/review-map/`.

The review maps share `client/booking/_review_map.html` and `BookingFormUI.updateReviewMap`, which reuses `BookingLocationMap.initReadOnly`. Independent review reported no substantive issues. No backend or payment-policy change was needed for these UI additions.

After the user's UI feedback, **50 focused regression tests and 5 enabled browser tests passed**. A final rerun of the 3 request-review browser tests also passed after checking label/value left alignment and keeping badges beside their labels. Desktop/mobile light/dark screenshots were inspected in `.booking-followup-check/request-review-refinement/`.

Browser assertions verify the original icon/label/value structure, transparent rows without left borders, requested-only item/price rows, absence of Added/Removed summary badges and the Payment Breakdown heading, and short payment copy. Existing retry, payment-state changes, excess confirmation, picture submission, custom-design, and normal-edit checks remain covered. The backend payment rules were unchanged by this refinement.

### Original implementation run

**127 booking tests passed**, including **7 enabled real-browser tests**: 3 new review flows, 2 existing change-feedback flows, and 2 existing four-step booking flows.

The run covers the unpaid/partial/fully-paid payment matrix, higher/equal/lower totals, overpayment, multiple verified credits and excluded payment states, saved/legacy prices, ownership, stale booking/reference/custom-design data, preview quota isolation, and read-only preview behavior. Browser checks cover reverting to no changes, current/requested package differences, optional removal, pin/landmark changes, image add/removal, failed-preview retry, verification arriving during editing, fresh excess cancellation/acceptance, unpaid/overpaid states, custom designs, direct edit after closing the same modal, and actual change-request submission retaining the original booking.

**24 request-protection tests passed; 2 concurrency tests were skipped by their existing conditions.** JavaScript syntax checks, Django system checks, and whitespace checks passed for the changed files.

Desktop/mobile screenshots at 1440px and 390px in light/dark themes were generated and inspected. Review content has no horizontal overflow at those widths. The existing four-step browser regressions also exercise their wider set of viewports. Screenshots and raw test logs are in the ignored local directory `.booking-followup-check/request-review/`.

An independent reviewer checked this task against pre-edit snapshots so unrelated workspace changes were excluded. Findings about rate budgets, legacy prices, custom-design thumbnails/versioning, overpayment explanations, and refreshed excess acknowledgment were fixed and regression-tested. The final review reported no remaining substantive findings.

The initial tests were observed failing for missing original data/payment review. Additional regressions were observed failing for legacy item identity, preview submission-budget consumption, custom-design serialization, overpayment explanation, and stale custom-design data before their fixes.

```powershell
$env:RUN_BOOKING_CHANGE_REVIEW_BROWSER='1'
$env:RUN_BOOKING_CHANGE_FEEDBACK_BROWSER='1'
$env:RUN_BOOKING_FOUR_STEP_BROWSER='1'
./.venv/Scripts/python.exe manage.py test app.test_booking_change_review app.test_booking_change_feedback app.test_booking_changes.BookingChangeTests app.test_change_payment_overview app.test_change_checkout app.test_change_request_actions app.test_booking_form_parity app.test_booking_change_review_browser app.test_booking_change_feedback_browser app.test_booking_four_step_browser --settings=Project.test_settings --noinput
./.venv/Scripts/python.exe manage.py test app.test_request_protection --settings=Project.test_settings --noinput
./.venv/Scripts/python.exe manage.py check --settings=Project.test_settings
node --check static/js/booking_change_review.js
node --check static/js/booking_changes.js
git diff --check -- app/booking_changes.py app/request_limits.py Project/settings.py app/views/changes.py app/templates/client/customer_profile.html static/css/booking_changes.css static/js/booking_changes.js
```

## Limits

These are local focused/regression results, not a full-project or deployed-environment certification. An earlier broader run that included `BookingChangeConcurrencyTests.test_concurrent_quotes_cannot_hold_the_same_schedule` hit the existing SQLite `database table is locked` limitation previously recorded in booking-change verification; the final booking run explicitly selects the non-concurrency `BookingChangeTests` class. PostgreSQL concurrency was not verified here.

No deployment, database migration, payment transaction, or payment-policy change was performed. Existing unrelated uncommitted work was preserved; task files were left in the workspace without committing unrelated changes.
