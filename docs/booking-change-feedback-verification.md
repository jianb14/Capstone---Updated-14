# Booking change feedback verification

Verified locally on November 10, 2026. No deployment, migration or payment-policy change was performed.

## Resulting behavior

- New-booking confirmation explains that changes after confirmation go through My Bookings and require approval, availability and the change-request deadline. The action is Submit Booking.
- Request Changes checks current eligibility before opening the reason dialog or wizard. Received payments under review produce a top-right notification immediately. The server checks again at submission.
- Verified full and partial payments remain eligible when other booking rules allow changes. An unpaid PayMongo checkout does not count as received funds.
- A lower estimated booking total triggers a confirmation only when it falls below the original total and verified payments exceed that estimate. The estimate includes package, extras, logistics and overtime through the existing price calculator.
- Cancelling the warning, including with Escape, preserves the previous package/add-on/additional selection. Partial payments below or equal to the revised total do not produce an excess-payment warning.
- The warning identifies amounts as estimates and retains the policy's stated exceptions. Admin review and the existing explicit customer acknowledgment of the exact final excess remain required.

## Checks

**18 request/payment regression tests passed**: 10 new entry-check tests plus 8 existing tests for preserved booking/payment records, upgrades, partial payments, pending proofs, downgrade review, final-quote excess acknowledgment, no-excess deposits and changed payment amounts after a quote.

**2 real-browser tests passed** with Chrome. They cover payment changes after the list page loads, blocking before any reason/form is shown, entry after verification without reloading, package downgrade continue/cancel, extra-item cancellation, keyboard Escape, a partial payment of PHP 7,500 against a revised PHP 8,000 total, and ordinary pending-booking edits. Screenshots were inspected at 1440px and 390px in light and dark themes. No JavaScript page errors occurred.

The initial request and browser checks were observed failing before implementation. Additional browser checks reproduced omitted logistics after deselecting a package and missing cancellation preservation for extras; both were corrected and retested.

```powershell
./.venv/Scripts/python.exe manage.py test app.test_booking_change_feedback --settings=Project.test_settings --noinput
$env:RUN_BOOKING_CHANGE_FEEDBACK_BROWSER='1'
./.venv/Scripts/python.exe manage.py test app.test_booking_change_feedback_browser --settings=Project.test_settings --noinput
./.venv/Scripts/python.exe manage.py check --settings=Project.test_settings
node --check static/js/booking_changes.js
git diff --check
```

The expanded 18-test payment run and all other raw results are recorded in `.booking-followup-check/booking-change-feedback-*.log`. Browser screenshots are in `.booking-followup-check/booking-change-feedback/` (ignored local artifacts).

An independent reviewer examined the changes. Two pricing/selection findings were resolved with browser regression checks; the final read-only review reported no remaining substantive findings.

## Full-suite limits

The full suite ran **1,490 tests: 13 failures, 2 SQLite concurrency errors, 206 skipped**. The set of all 15 failing test identifiers exactly matches the earlier baseline documented by name in `docs/error-pages-verification.md`; there were no newly failing identifiers. That baseline was also reproduced with custom error handling disabled. Unrelated dashboard/template/staticfile expectations and SQLite concurrency tests were left unchanged.

Browser tests were explicitly enabled separately. The final pricing-selection refinements were verified by the focused request/payment and browser runs after the full suite had started. The full project suite is not green, and local results do not verify the deployed Railway environment.
