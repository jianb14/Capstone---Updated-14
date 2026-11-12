# GCash QR payments

New payments use the configured merchant QR and website proof submission. The system does not automatically verify a transfer. An administrator must match the actual successful incoming merchant transaction before approving it.

## Rollout

1. Back up the application database and apply `python manage.py migrate` during deployment. Migration `0119_gcash_qr_proofs` adds nullable payment fields; it does not rewrite or delete historical payments. It was applied to the verified loopback/local PostgreSQL instance on 2026-11-12 after `pg_dump` backup and `pg_restore --list` validation. No hosted database was changed. The local backup is `.booking-followup-check/database-backups/before-gcash-qr-20261112-223929.dump`.
2. The client supplies its official merchant QR, exact recipient name, optional account number, and payment instructions. Confirm with GCash that the merchant product is suitable for online booking collections and review the applicable fees and limits.
3. In Payments → Payment Settings, upload a PNG/JPEG QR and enter the recipient name. Verify the displayed QR using the client's GCash/merchant account before accepting customer payments. An absent QR or recipient disables new submissions.
4. On Cloudinary deployments, proof uploads use authenticated delivery. Keep the existing Cloudinary credentials server-side. Without Cloudinary, set `PAYMENT_PROOF_ROOT` to a durable private directory outside public `MEDIA_ROOT` and back it up. The default is `private_payment_proofs/`, excluded from Git.
5. Keep PayMongo reconciliation credentials and the signed webhook active while previously created sessions remain unresolved. The old checkout creation route no longer creates or resumes charges. An unresolved previous checkout blocks QR submission until a provider-confirmed terminal state or a received payment is recorded. Browser cancellation alone is not confirmation of provider expiry.
6. Verify one client-controlled collection operationally before launch: QR recipient and amount, merchant transaction record, customer proof, admin verification, notification, and remaining balance. Do not use invented recipient details or real customer data for testing.

## Customer and admin behavior

- Initial bookings offer downpayment or full payment; verified deposits expose the remaining balance. A 100% downpayment is recorded as full payment.
- Accepted booking changes charge the saved additional quote separately. The original booking is unchanged until verification and valid quote application.
- Proof requires a reference, sender, customer-reported transaction date/time, and a valid PNG/JPEG of at most 5 MB/12 megapixels. Images are decoded and re-encoded; the website never asks for an OTP or MPIN.
- Server-side submission time controls deadline eligibility. The customer-reported transaction time cannot backdate a submission or reopen an expired booking.
- Reference normalization removes whitespace/hyphens and uppercases letters. New pending/verified references have a database unique reservation; existing active references are checked too. Rejection releases the new reservation and allows a corrected submission.
- Recipient details are signed when the form is displayed and copied onto the payment. Later settings changes do not rewrite payment history.
- Only the owner and administrators can retrieve proof through `/payments/<id>/proof/`. Responses are private and must not be cached. Admin approval of new QR proofs requires explicit acknowledgement that the incoming transaction was checked in the merchant account.
- A submitted screenshot is a claim awaiting review. Only verified payments count toward the booking balance. Existing deadline alerts protect submitted proofs while the team checks them; late funds do not automatically reopen closed reservations.
- For a missing merchant transaction, incorrect recipient, under/overpayment, or an expired quote, resolve the actual transfer with the customer before asking for another payment. Rejection does not issue a refund.

## Historical proof privacy

Historical proof filenames still read through their original storage so payment history remains usable. Previously public local/Cloudinary files are not made private merely by changing the website's links. If historical proofs exist, the operator must separately copy them into private storage, verify their readability, update the corresponding payment filenames, and revoke/remove the old public copies after backup. Never delete the only copy of financial evidence. No external asset migration or deletion is performed by this change.

## Verification records

Automated checks use `Project.test_settings` (in-memory SQLite, local test email, temporary storage). The regression suites include QR settings, initial/full/balance/change submissions, duplicate references, invalid images/amounts, recipient snapshots, proof permissions, approval/rejection, deadlines, and provider reconciliation. Cloudinary upload/read tests mock the official authenticated delivery interface; live provider access remains an operator rollout check.

Browser verification uses `RUN_DESIGN_BROWSER=1` and the local Edge executable, isolated test accounts, and blocked third-party browser traffic. Screenshots/logs are written only to `.booking-followup-check/`. Detailed results: [verification record](gcash-qr-verification.md).
