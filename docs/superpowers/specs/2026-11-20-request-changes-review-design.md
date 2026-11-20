# Request Changes: Review & Confirm comparison

Status: Approved by the user, including the payment clarification; implementation authorized on November 20, 2026.

Visual refinement requested after implementation: preserve the original review UI, including icons, label/value rows, price alignment, and Total Price styling. Remove change callout backgrounds and left borders. Use small soft badges and a muted Previously annotation on changed details. Booking Summary lists requested items only, with no Added/Removed badges or removed-item duplication. Replace the separate Payment Breakdown section with verified payments, estimated remaining, and one short conditional explanation inside the existing summary. This refinement supersedes the more verbose visual/copy examples below; calculation and validation requirements remain in force.

Additional requested refinement: show Changed beside changed requested item and fee labels; align Current total with its amount and put the price delta beneath. Group reference pictures by status with badges in their field headers. Show a read-only map with the selected venue pin in Step 4 of new booking, direct editing, and change requests; refresh it from current form/proposal coordinates and clear it when no valid pin is available.

Replaced package/extra summary rows show Changed and Previously with the saved predecessor's name and price, matched by package/solo, add-on, or additional slot. A genuinely new item shows Added with no Previously annotation. Keep unavailable historical prices explicit and omit the annotation for unchanged rows.

Overtime notes in create/edit/request forms use a compact neutral surface, clock icon, started hours and rate, and the added fee aligned right. Keep the rate visible before overtime is selected; once the fee note is visible, remove the duplicate rate sentence from the included-window hint. Preserve existing charge calculation and confirmation behavior.

Pending-booking refinement: direct pending edits also compare the review against the owner's saved booking, with Changed/Added/Removed and Previous annotations in the same existing cards. Obtain a fresh owner-checked baseline from the existing edit endpoint. Keep pending edits on the direct Update Booking flow, without a change reason, request-payment explanation, quote, or BookingChangeRequest. Preserve ordinary direct-edit validation and pricing. Custom designs without catalog selections retain their saved base price. Ignore stale asynchronous opens when another booking is selected or the modal closes.

Map/focus refinement: review has one Map Pin field containing the current preview and an Added/Changed badge when applicable. Remove the separate textual Map Pin comparison and Venue Map label, including Previously: Pin saved. Event Details and Design Preferences validation use the same visible-control focus and centered smooth scrolling, respecting reduced-motion preferences. Preserve distinct success, loading, and error colors on editable-map feedback in both themes, including required-pin validation messages.

Loading-color correction: Finding your current location and other map-loading feedback use the form's muted gray in both themes. Success remains green and errors remain red.

Submission confirmation wording approved by the user:

- New booking: **Submit your booking request?** / Please review your event details, venue pin, and selected items. Our team will review your request and notify you once it’s approved. / **Review Again** and **Submit Request**.
- Pending direct edit: **Save your booking changes?** / Please check your updated details. Your booking will remain pending for review. / **Review Again** and **Save Changes**.
- Change request: **Submit your change request?** / Our team will review your changes and send a final quote. Your current booking stays unchanged until the changes are finalized. / **Review Again** and **Submit Request**.

These dialogs appear after review, before the actual POST. Cancellation leaves the draft available without submitting. Existing validation and submit behavior remain authoritative.

No-change/motion refinement (updated per user correction): show both the existing top-right info toast and a muted-gray message immediately above the submit actions: No changes yet. Go back and update at least one detail to submit your request. The inline message has no icon; hide it on editing/reset. Keep submit disabled while unchanged. Keep checking/error feedback and Retry above the grid. Request-mode booking/reason banner replays its existing 400ms fade-in at every step change (Next and Back), with form content following after a 140ms stagger. Also animate on initial opening; respect reduced-motion preferences and keep ordinary pending-edit animation unchanged.

The disabled review submit button must also look disabled in both themes: muted surface/text, reduced opacity, not-allowed cursor, and no active hover styling. Normal enabled styling returns after a valid changed draft is reviewed.

## Purpose

Before submitting a booking change request, customers should see their complete proposed booking and clearly identify what differs from their current reservation. Keep the existing Booking Details and Booking Summary cards. Explain that this is a request and that prices are estimates until the team provides its final quote.

The user requested a full proposed plan for review before implementation. This document records the recommended approach, including implementation order and acceptance checks, for that approval.

The user subsequently clarified that review must also explain verified payments already credited and what remains payable for unpaid, partially paid, and fully paid bookings. The proposed design below includes that payment-aware breakdown. Approval remains pending.

## Existing behavior

- The customer edit wizard already has four steps. Step 4 renders the selected details, reference images, item prices, logistics, overtime, and computed total through `populateEditSummary()` in `app/templates/client/customer_profile.html`.
- The same modal supports direct edits to pending bookings and reviewed change requests. `configureBookingChangeForm()` in `static/js/booking_changes.js` switches modes and the submit label.
- The authenticated change-request GET endpoint checks ownership and eligibility and returns verified payments and the original total. The wizard currently prefills most details from page-rendered booking data.
- Submission stores separate original and proposed snapshots. `app/booking_changes.py` handles the final quote, customer acceptance, additional payment, and application of changes. The original reservation remains in place during review.
- Existing saved fee policies can include historical catalog item amounts. Retained items must follow the existing saved-price rules rather than silently comparing old totals with newly repriced selections.

## Approaches

1. **Inline comparison in the two existing cards — recommended.** Show Current and Requested values only on changed rows. Unchanged rows show one normal value. This keeps the full booking readable and places differences where customers already review them.
2. **Separate Requested Changes section.** Consolidates differences in one place but repeats details from the existing cards and lengthens the modal.
3. **Replace the review with a changes-only table.** Compact for differences, but customers lose the full proposed booking context. Not recommended for this request.

Approach 1 was approved by the user along with the payment-aware breakdown.

## Customer flow and copy

1. Customer selects Request Changes and provides the existing required reason.
2. Customer edits Event Details, Select Package, and Design Preferences using the current wizard.
3. Review & Confirm displays the full proposed booking, with inline comparisons for differences.
4. Customer can use Back to revise selections. Returning to review recalculates differences against the same original reservation, not the previous draft.
5. Submit Change Request uses the existing submission and validation flow.
6. Submission success uses the existing confirmation and booking-details destination.

Keep the heading `Review & Confirm`. In change-request mode, use this description:

> Compare your current booking with your requested changes before submitting.

Keep the reason visible in the existing request banner. Replace the generic review note in change-request mode with:

> These changes are subject to approval and availability. Your current booking remains unchanged. Our team will send a final quote for you to review and accept.

Use English for product copy to match the existing interface. Direct pending-booking edits retain their appropriate existing copy and behavior.

## Booking Details

Always display the full proposed booking. Changed rows receive a visible text badge and a subtle background or border using existing theme styles. Do not rely on color alone.

```text
Package / Items                         Changed
Current:   Package 1-A
Requested: Package 1-B

Event Type
Birthday

Theme                                   Changed
Current:   Butterfly
Requested: Space Galaxy

Motto                                   Removed
Current:   Happy Birthday, Mia!
Requested: None
```

Compare these customer-facing groups:

- Package / items: package, add-on or solo selection, and additional items.
- Event type, including a custom Other value.
- Event date and start/end time with duration. Display overnight events clearly, including the end date when applicable.
- Location/address, landmark, and map pin. A pin change must be visible even when the address text is identical; present a useful Map pin updated/added/removed description rather than raw coordinate changes.
- Theme, color palette, motto/backdrop text, and design notes.
- Reference pictures: show retained pictures normally and mark added or removed pictures with text labels. Keep removed picture thumbnails visible in the review so the customer can verify the removal; do not delete stored files while reviewing.

Badge rules: Changed for an existing value replaced by another; Added for a previously empty optional value; Removed for a cleared value. Optional fields that were empty and remain empty can stay omitted. An optional value being removed must remain visible as a comparison row.

Compare semantic values: consistent time/date formats, coordinate precision, insignificant outer whitespace, and palette values independent of ordering when the selected colors are the same. Respect meaningful text changes. Comparing images must use existing image IDs and selected file state, not regenerated temporary preview URLs.

## Booking Summary

Keep the line-item breakdown. Label the price column/area as requested estimated prices. Retained unchanged lines show once; changed lines show their current and estimated requested amounts when saved amounts are available. Added and removed items remain explicitly identifiable. Removed items do not contribute to the estimated revised total.

Show logistics and overtime changes as well as package/extras changes. Match selections by their actual item identity and role; switching package-plus-add-on to solo must be represented correctly.

The totals area becomes:

```text
Current booking total                PHP 6,000.00
Estimated revised total              PHP 6,799.00
Estimated increase                     PHP 799.00
```

Use the existing peso currency formatter in the UI. The amounts above are illustrative, not actual prices for Package 1-A or 1-B. If the estimate is lower, show Estimated decrease with a positive readable amount. If equal, show No estimated price change. Round comparisons to currency precision.

Do not call the price difference Amount due or Pay now. Show credited payments and estimated remaining amounts using the payment-aware breakdown below. The actual required additional payment remains governed by the existing final-quote flow. Preserve the current downgrade/excess-payment warning and acknowledgment behavior. A lower estimated price alone must not imply a refund.

Use saved item amounts for the current side. Never reconstruct historical item prices using today's catalog or divide the saved total arbitrarily. Where a legacy booking has no saved line-item amount, retain its exact saved total and show its current item name with a small Price breakdown unavailable note. Requested amounts remain estimates. Existing saved-price and fee-policy rules for retained items must be respected; catalog changes must not appear as customer item switches.

## Payments already credited and estimated remaining balance

Add a Payment Breakdown area inside Booking Summary, below the price comparison. The purpose is to answer both questions: How much have I already paid? How much would I still need to pay for this requested booking?

Use verified payments actually applied to this booking as the credited amount. Sum each eligible payment once, including any verified payment from an earlier applied change. Never infer payment from the booking status alone, or include rejected payments, unpaid checkout sessions, pending verification, or payments belonging to another/unapplied request.

Do not label an individual package, fee, or add-on Paid unless the system records a real allocation to that item. Existing payments are booking-level credits; say Verified payments already credited.

Example for an original PHP 6,000 booking, PHP 3,000 verified payment, and a requested PHP 8,000 total:

```text
Payment Breakdown
Current payment status                  Partially paid
Verified payments already credited        PHP 3,000.00
Current unpaid booking balance            PHP 3,000.00

Estimated revised total                   PHP 8,000.00
Estimated total remaining to pay          PHP 5,000.00

Of that estimated remaining amount:
  For this change, after quote acceptance PHP 2,000.00
  Booking balance after that payment      PHP 3,000.00
```

The two final amounts are parts of PHP 5,000, not extra charges on top of it. Display that relationship explicitly. The change amount remains Estimated until the final quote. Use the label Current payment status because a currently fully paid reservation can still have a balance under a more expensive request.

Existing policy must remain consistent: when there is already a verified credited payment and the price increases, the price increase is the separate change payment required after quote acceptance. Any original unpaid booking balance remains separate. When nothing has been paid, the requested total is the estimated booking balance; no separate change top-up is required by the current change-approval policy. Explain that booking-payment requirements and deadlines still apply; do not describe the unpaid booking as settled or free.

Calculate the displayed preview consistently with the existing server payment-summary rules. With original total O, estimated revised total R, and verified credited payment P, all at currency precision:

- Current unpaid booking balance = max(O - P, 0).
- Estimated total remaining to pay = max(R - P, 0).
- Estimated payment to finalize this change = max(R - O, 0) when P > 0; otherwise 0, per the existing policy.
- Estimated booking balance after that change payment = max(R - P - estimated change payment, 0).
- When the requested total is lower and paid credits exceed it, estimated excess payment = max(P - R, 0).

Reuse the existing payment-summary logic on the server where practical; expose a small preview amount calculation if required rather than creating an independent payment policy in JavaScript. Browser display calculations never authorize a payment or change final quote amounts. No new payment checkout or Pay now action is added to Step 4.

Required cases (illustrative amounts):

| Current total | Verified paid | Requested total | Estimated total remaining | Separate estimated change payment | Booking balance after change payment | Estimated excess |
| --- | --- | --- | --- | --- | --- | --- |
| 6,000 | 0 | 8,000 | 8,000 | 0 | 8,000 | 0 |
| 6,000 | 3,000 | 8,000 | 5,000 | 2,000 | 3,000 | 0 |
| 6,000 | 6,000 | 8,000 | 2,000 | 2,000 | 0 | 0 |
| 6,000 | 3,000 | 6,000 | 3,000 | 0 | 3,000 | 0 |
| 6,000 | 6,000 | 6,000 | 0 | 0 | 0 | 0 |
| 6,000 | 3,000 | 5,000 | 2,000 | 0 | 2,000 | 0 |
| 6,000 | 6,000 | 5,000 | 0 | 0 | 0 | 1,000 |

For no-price-change or lower-price requests, show No additional payment for this change where useful, while keeping any remaining booking balance visible. For an unpaid booking, explain that the estimated full booking balance is still unpaid instead of showing an ambiguous zero payable figure.

For a lower requested total with estimated excess, show Estimated excess payment separately. Preserve the existing payment policy, its exceptions, and the final-quote acknowledgment; do not promise a refund or transferable credit. Never show a negative remaining balance.

Received payments awaiting verification remain excluded from verified credits. The current policy blocks opening/submitting change requests while such a payment is under review. Keep that behavior and explain why rather than marking it as unpaid or counting it as credited. Merely opening an unpaid payment-provider checkout does not count as received payment.

Refresh payment state when entering review using the existing owner-checked endpoint, retaining the original detail baseline for comparison. If the saved reservation itself changed since the wizard opened, require reopening the draft with a fresh baseline rather than silently mixing versions. If a payment becomes pending verification while the wizard is open, prevent submission with the existing feedback. If the refresh fails, show an inline retry message and keep submission unavailable until current payment/eligibility state can be checked. Submission-time verification still runs.

Implementation rulings: use a read-only review POST on the same owner-checked endpoint to reuse authoritative proposal calculations, with its own bounded preview quota (30 per minute) instead of the submission quota. Recheck excess-payment confirmation against the refreshed preview before enabling submission. Include saved custom-design thumbnails in the baseline/version. If existing overpayment makes the policy's separate change top-up exceed the estimated unpaid balance, replace the usual component explanation with a team-review explanation; keep the existing policy and show the actual estimated unpaid balance.

## Comparison state and validation

- Extend the existing owner-checked change-request GET response with the minimum original review data needed: booking detail values, saved pricing information, and existing reference image identities/URLs. Return only data belonging to the authenticated customer's booking.
- Use that same response as the change-request prefill and original comparison baseline. This avoids comparing a fresh original total against older details embedded when the page loaded.
- Keep the baseline unchanged while moving through the wizard. Read proposed values from current form and selection/upload state every time review opens.
- Revert a field to its original value and its badge disappears. Removing a newly added file before submission also removes its Added entry.
- When no customer-editable details or image selections differ, show `No changes selected. Go back and update at least one booking detail.` and disable Submit Change Request. A reason or an automatic price recalculation alone does not count as a customer change.
- If the baseline cannot be loaded, show the existing error feedback and allow retry by reopening Request Changes; do not display an invented comparison.
- Preserve submission-time ownership, eligibility, payment verification, availability, and pricing validation. Review is a preview of a draft; server validation and the final quote remain authoritative if availability, prices, or booking state change while the form is open.
- Clear baseline, comparison markup, and upload preview object URLs on close or switching bookings, including when moving from request mode to normal edit mode.
- Render customer-entered text safely using the existing escaping/text rendering patterns.

## Layout and accessibility

- Desktop keeps the two-card layout. Narrow screens stack the cards and Current/Requested values vertically without horizontal scrolling.
- Reuse existing typography, spacing, badges, and light/dark theme variables. Keep changed values readable, including long locations and notes.
- Text badges distinguish changes without requiring color perception. Image thumbnails have meaningful labels/alt text for retained, added, and removed status.
- Preserve keyboard navigation and visible focus. Explain a disabled submit button through a visible message.

## Scope and boundaries

This is a focused enhancement to the customer's Request Changes review step. No database migration, new wizard step, new dependency, or new approval/payment policy is planned. New-booking checkout, direct pending-booking editing, admin quote screens, notifications, and post-submission comparison/history screens keep their existing behavior. Any existing unrelated workspace edits must be preserved.

## Proposed implementation order after approval

1. Extend the existing eligibility response with original review data and current verified payment state; cover ownership, historical-price fallback, and payment-summary calculations.
2. Add the small comparison-state/helper logic to the existing booking-change script; align change-request prefilling with its baseline and refresh payment/eligibility state on review entry.
3. Update Step 4 detail, image, item, total, and Payment Breakdown rendering in the customer template, retaining its existing fee calculation and validation rules.
4. Add scoped responsive and theme styles to the existing booking-change stylesheet.
5. Verify request-mode behavior and regression-check ordinary editing and new booking review; record results and screenshots.

Likely files: `app/views/changes.py`, `static/js/booking_changes.js`, `app/templates/client/customer_profile.html`, and `static/css/booking_changes.css`, with focused tests alongside existing booking-change and browser tests. Reuse pricing helpers in `app/booking_changes.py` where appropriate; do not duplicate final quote/payment formulas in the browser.

## Acceptance checks

- Change one detail, several details, and only design notes; only affected rows receive badges.
- Switch packages, add/remove extras, and switch to/from solo selections; item status and price comparisons remain correct.
- Change schedule or venue so logistics/overtime changes; display both detail and fee differences accurately.
- Add, remove, and replace reference pictures, including legacy single-image bookings and the existing four-picture limit.
- Remove an optional motto/landmark/note; the removed value remains reviewable.
- Revert changes to the original values; badges disappear and no-change submission becomes unavailable.
- Verify higher/lower/equal estimated totals, saved historical item prices, and missing historical item-price data.
- Verify unpaid, partial, and fully paid cases in the payment table; the total remaining and its component amounts must reconcile without double-counting.
- Sum multiple verified payments once; exclude rejected/pending/unapplied payments and unpaid checkouts. Include earlier applied change payments once.
- Confirm current payment status is distinguished from the requested booking's estimated balance, and that no item-level payment allocation is fabricated.
- Recheck after payments change during editing, including a newly pending verification or a failed payment-state refresh; keep submission-time enforcement.
- Verify existing downgrade warnings with verified payments and without an estimated excess; do not introduce new refund claims.
- Reopen the wizard or switch bookings; no old comparisons, removed image markers, or preview URLs remain.
- Test unauthorized baseline access and failed baseline loading; do not expose or fabricate booking data.
- Submit a valid request and confirm the live booking remains unchanged pending the existing approval/finalization process.
- Check desktop/mobile, light/dark themes, long values, keyboard access, and safe display of customer text.
- Regression-check direct pending-booking edits, new-booking review, and existing change-request validation/quote/payment tests.

Approval selects the inline-comparison approach and the scope above. Implementation and verification are tracked in the associated implementation plan.
