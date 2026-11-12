# GCash QR payments

The client wants to replace new PayMongo checkouts with GCash QR payments. The user approved the proposed manual-verification flow and authorized careful implementation across connected features on 2026-11-12.

## Approach

Use the client's configured merchant QR, collect proof in the application, and require an administrator to verify the incoming transaction in the merchant account. An automatic QR integration would require separate provider onboarding and server confirmation; that is outside this change. The site never requests a GCash MPIN or OTP.

## Behavior

- One payment screen supports initial downpayment/full payment, remaining balance, and accepted booking-change top-ups. Amounts come from saved server-side prices and quotes.
- Admin settings manage the recipient, optional account number, QR image, instructions, and existing downpayment percentage. Missing recipient/QR blocks new submissions with a helpful unavailable state.
- Customers see the amount, recipient, QR download, deadline, and review expectations. Proof requires a valid bounded PNG/JPEG, reference, sender, and transaction date/time. Submission remains pending and does not confirm the booking.
- A normalized reference is reserved uniquely in the database for each new pending/verified manual payment. Legacy active references are also checked. Rejection releases the reservation so a corrected submission is possible.
- New proof files are private: outside public media for local storage, authenticated assets on Cloudinary. Only the owner and admins can retrieve proof through an authenticated endpoint. Legacy proof storage remains readable without deleting historical records.
- An administrator explicitly acknowledges checking the actual merchant transaction before approving new QR proofs. Preserve existing booking deadline alerts and the rule that late payments cannot reopen closed bookings or apply expired changes.
- New PayMongo checkout creation and resume links stop. Existing IDs, records, receipts, return routes, and signed webhook reconciliation remain for already-created payments. Surface unfinished legacy transactions for review before another payment.
- Update customer payment tracking, admin details/confirmation, notification instructions, and chatbot payment knowledge consistently.

## Constraints and operational requirements

Preserve unrelated user edits, existing payment history, and the current Django/UI stack. Do not change a hosted database or make real financial transactions. A verified local database may receive the additive migration after a validated backup. The client must supply and verify the actual merchant QR; do not invent an account or claim merchant onboarding is complete. Existing public Cloudinary proof URLs require a separate operator-controlled privacy migration; document this limit.

## Verification

Exercise settings permissions/validation, unavailable state, initial/full/balance/change submissions, duplicate references, manipulated amounts, invalid images, proof access, manual approval, rejection/resubmission, deadlines, legacy callbacks/history, and chatbot guidance. Run the isolated Django suite and browser checks for customer and admin forms at phone/tablet/desktop sizes.
