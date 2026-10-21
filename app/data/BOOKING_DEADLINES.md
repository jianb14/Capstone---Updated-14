# Booking deadlines

- Site Settings controls the initial payment window and missing design warning (both default to 24 hours).
- Approval saves the payment deadline as the earlier of approval + payment window and the event's local start time. Saved deadlines do not move when settings change.
- An unapproved request expires at the event start. Legacy bookings without a start time retain the booking through the end of that date.
- Submitted manual proofs and successfully received provider payments are protected during verification. An abandoned checkout does not count as received payment.
- The team receives a repeat-safe overdue verification alert after 24 hours or at event start, whichever comes first. Design warnings start at the saved design deadline and never expire confirmed bookings.
- Pre-existing approved bookings without a saved deadline receive a visible grace window on their first processing pass, capped at event start.
- Late provider receipts and verification against expired/cancelled bookings retain the payment record and flag a team review; they never reopen the reservation automatically.

The development `runserver` process starts a deadline thread after autoreload; `--noreload` is supported. Railway's Gunicorn configuration starts the thread after worker initialization. Processing runs on startup and every minute while the server process is running. Multiple workers serialize changes using booking row locks and unique notice keys. A sleeping/stopped hosting service cannot run its threads; keep the web service running or schedule `python manage.py process_booking_deadlines` on an always-running scheduler.

`python manage.py process_booking_deadlines` runs one pass for operations and scheduler integrations. Tests and migrations do not automatically start the thread.
