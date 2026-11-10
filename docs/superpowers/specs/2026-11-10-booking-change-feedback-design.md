# Booking change feedback

The user approved implementation of the discussed English confirmation copy, early eligibility feedback and downgrade warning. Preserve the existing booking-change approval, payment verification and final-quote acceptance policies.

- New booking confirmation explains that post-confirmation changes go through My Bookings and require approval, availability and the change-request deadline. Use Review Again and Submit Booking actions.
- Before opening a change reason dialog or wizard, query the existing owner-checked change-request endpoint. If a received payment is awaiting verification, show the existing top-right toast and leave the form unopened. Keep submission-time enforcement and permit fully verified payments. Do not treat an unpaid PayMongo checkout as submitted funds.
- Use fresh verified credited payments and the original booking total returned by that endpoint. When a package/selection produces a lower estimated booking total with actual estimated excess, show the existing accessible confirmation modal before continuing. Cancel retains the previous selection. Explain that the amount is an estimate and policy exceptions still apply; final amounts and acknowledgment remain in the final quote.
- Do not show a nonrefund warning where partial payments are below or equal to the revised total. Do not modify any payment/refund policy or booking record merely to preview changes.
- Reuse existing feedback and modal styles; support mobile, keyboard and both themes. Recheck eligibility at submission even if entry was allowed.

Verification covers pending GCash/received PayMongo, unpaid checkout, verified full/partial payment, ownership, cutoff/active requests, changed state after page load and after opening, warning continue/cancel, no-excess cases, final-quote acknowledgment, and normal pending-booking edits.
