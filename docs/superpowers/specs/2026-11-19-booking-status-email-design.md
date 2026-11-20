# Customer booking emails

Approved scope: email customers on submission, approval/pending payment, confirmation,
cancellation/denial, expiration and completion. Preserve existing in-app notices.
Include booking number, event schedule, status, relevant reason, payment amount and
deadline on approval, and a link to the authenticated booking page.

Approaches: individual view calls risk missing deadline-worker and payment-sync
transitions; watching Booking saves loses audit reasons and sees intermediate saves.
Use the existing BookingStatusLog creation event shared by every current transition.
Ignore history-only entries and updates to existing logs. Schedule immutable email
content after commit, so rollbacks send nothing and provider failures preserve data.
Use the existing email backend; no new dependencies or migration. No automatic retry
when provider acceptance is unclear. No historical backfill or marketing email.

Builder decisions: plain text consistent with existing transactional mail; resolve
public origin from explicit BOOKING_EMAIL_BASE_URL, Railway domain, concrete trusted
origins, or concrete allowed hosts. Missing public origin must be logged safely.
