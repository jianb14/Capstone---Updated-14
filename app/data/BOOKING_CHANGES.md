# Customer booking changes

Pending bookings keep direct Edit. Approved / confirmed bookings use the same
five-step form in request mode, with a required reason. The form posts to a
separate owner-protected endpoint and never edits the live reservation.

Request Changes first opens the existing SweetAlert dialog for a 10–2,000
character reason. Cancel/Escape leaves the booking untouched. Continuing opens
the edit wizard with the reason shown as text in its banner and included as a
hidden POST field; Step 5 has no duplicate reason textarea. Pending-booking
direct edits skip this dialog. The server still validates the submitted reason.

The team reviews the original versus requested details in Change Requests.
The admin workspace now has two tabs in Booking Management: Bookings and Change
Requests. Requests have their own active/history lists, search, status filter,
and pagination. The badge counts requests needing team review, manual attention,
or verification of a submitted change payment; unpaid provider checkouts do not
increase it. Requests needing action sort first.

Review Request opens `/staff/booking-changes/<request_id>/`, which shows that
specific request using the shared review partial. Booking Details contains a
compact link to the active request, or the newest closed request when none is
active. Review forms and notifications open the dedicated request page. Review
actions return there and retain the list filters via a validated local return
URL. Closed history is read-only, with saved quote payment figures; later
bookings or payments do not rewrite the historical quote. The customer interface
and payment verification endpoints retain their existing flows.

Approving sends a final quote for customer acceptance; it does not apply changes.
One active request is allowed per booking. The default request cutoff is 48 hours
before the original and proposed event; edit it in Site Settings → Booking Rules.

## Quoting and payment

The proposed quote is calculated on the server. Unchanged package selections,
saved unit prices, venue fees, and duration terms retain their booked prices.
Changes to the venue clear a venue-specific manual logistics override and use a
new logistics quote. Changed duration uses the current duration policy. New
catalog selections use current prices, retaining saved unit prices for unchanged
items when those historical prices are available. Legacy bookings have a saved
aggregate price rather than invented historical unit prices.

Quotes last for the configured initial payment window (24 hours by default),
capped at the earlier original/proposed event start. Their proposed slot is held
alongside the original reservation. Shared availability, create/edit validation,
and admin approval include these holds. Reservation writes take the SiteSettings
row lock before booking/request/payment locks to serialize conflicting quotes.

An unpaid approved booking accepts its quote without an amendment payment; its
normal initial payment uses the revised total, with no extension to its original
payment deadline. If any original payment is verified, a price increase requires
only the difference between original and revised totals. Existing unpaid balance
remains payable normally. Team verification of the additional payment applies
the accepted change atomically. The same receipt cannot be submitted twice.

My Payments > Action Required lists accepted changes with an additional amount,
their payment deadline, and a link to the protected change-payment flow. Unaccepted
quotes are not listed as debts. Submitted proof replaces the payment button with
Payment under review; an unpaid checkout keeps the action available. Manual-review
requests show a contact/review message without another payment button. Original
balances stay separate in Remaining Balances, with payment paused while change
proof is being reviewed. Applied, withdrawn, declined, and expired changes leave
the action queue. Change payments are identified in history, and their Payment
Info / retry links never send the customer to the original booking checkout.

My Payments and the booking-details modal use the same recorded-funds action
guard. A received pending payment shows Payment under review / View Payment
Status and hides Pay Additional and Withdraw. Recorded verified funds also
prevent another payment even if finalization requires manual handling. An
unfinished unpaid checkout is not treated as a received payment. The existing
server-side withdrawal and duplicate-payment checks remain authoritative.

Initial, balance, and additional change payments render the same
`client/payment_upload.html` checkout, using the existing three steps, consent,
booking sidebar, order summary, and GCash via PayMongo flow. A change payment
has a fixed amount from the accepted quote; it never offers downpayment/full
booking options or trusts a posted amount. Its summary shows original/revised
totals, existing verified payments, the additional due, and any separate original
balance. Submitted payments use the same verification screen. The change endpoint
and owner checks remain in place, including provider success/cancel/processing
returns and reuse of unfinished checkouts. Manual receipt POST compatibility is
retained for existing records; the separate manual-proof checkout page is removed.

Change payments use existing Payment records, linked to BookingChangeRequest,
with `applied_to_booking=False` until finalization. Such records remain in payment
history and receipts, but do not change the original booking's settlement status
or balance. Verification is repeat-safe. Expired/closed quotes, changed originals,
late/duplicate payments, or past events require manual resolution and never
silently alter the original booking or issue a refund/credit.

A lower-priced booking requires the excess-payment acknowledgments only when
verified payments actually exceed its revised total. The team must explain the
exact non-refundable excess under the existing checkout payment policy in the
customer-visible message before sending a quote. The customer must separately
acknowledge that amount before accepting; the acknowledgment time is recorded
in the saved quote and audit history. The existing policy and its exceptions
continue to apply. Upgrades and deposit-only downgrades without an excess show
neither refund acknowledgment. If later verification changes the excess amount,
the quote goes back for team review before acceptance. Existing unpaid balance
is shown separately from any additional change payment. There is no automated
refund/credit ledger.
An exceptional received payment can be recorded as manually resolved and the
request closed after verification/rejection; the original ledger is preserved.

## Expiry and design revisions

The existing minute worker and `process_booking_deadlines` management command
also process change quotes. Unpaid expired quotes release their proposed slot
and keep the original booking intact. Timely submitted proof keeps a future
proposed slot held while awaiting verification and creates one urgent warning.
Once an event has started, the request goes to manual review and releases its
proposed hold. Original payment deadlines still apply to unpaid bookings.

Final design-affecting changes mark earlier deliveries as previous designs and
show Design Revision Pending until a new delivery is uploaded. Existing design
files are not deleted. Current upload limits still apply; the team can manage
deliveries using the existing upload/delete controls.

Migration: `0096_booking_change_requests` adds the request/image records, payment
link and settlement flag, and configurable change cutoff. All existing payments
remain applied by default. Legacy edit-request flags are intentionally unused.
Migration `0097_preserve_change_payment_history` prevents deleting a request with
payment history on its own while retaining the existing full booking/account
cascade behavior.
