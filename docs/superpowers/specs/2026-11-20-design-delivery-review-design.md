# Missed design delivery review

Approved scope: the conversation's December 30 event / December 31 missing-design example, authorized with “okay go”.

## Behavior

- Keep booking and payment records intact. No automatic cancellation or completion.
- Before the event ends, a missing design is preparing or overdue; notify the team and customer once per design cycle when overdue.
- At the actual event end (including overnight events), a confirmed booking without its current design needs admin action. Use the existing scheduling helper's legacy end-time and four-hour fallback; unknown start times retain the booking through its saved end date or event date.
- A late upload remains available but cannot silently close the missed-delivery issue. Preserve its delivery timestamp and deadline snapshot.
- Persist a review per initial design or applied design revision. Admin records external delivery (actual delivery time), late online delivery, or the agreed customer resolution, with customer-visible notes and an explicit service-fulfilled declaration. All resolutions retain actor and timestamp. A resolution without fulfilled service cannot enable Completed.
- Only admins may resolve; validate POST, current design revision, required notes, actual delivery timestamps, and delivery existence. Serialize resolution, uploads, deletion, and completion on the booking row. Retries do not create duplicate notifications or history.
- Completion requires the event to have ended and any missed-delivery issue to be resolved with fulfilled service. Existing cancellation and payment rules remain responsible for cancellation/payment outcomes.
- Customer and admin views distinguish overdue, missed delivery, late upload, and resolution. Customers must not see “in preparation” after the event ended.

## Approaches

The discussion selected overdue warnings followed by a persistent admin review. Automatic cancellation would discard a paid service obligation; automatic completion would falsely imply fulfillment. A computed warning alone would disappear after a late upload and cannot record a resolution.

## Implementation decisions

Use one small review model keyed by booking and design cycle, the existing lifecycle processor and notifications, and the existing admin design dialog's async forms. Reuse current layouts, colors, validation, history, and customer booking views. No new dependencies, refund automation, or redesign.

## Verification

Test exact end-time boundaries, overnight and legacy schedules, repeat processing, late upload before the worker runs, validation/authorization, completion bypasses, deletion reopening, revision isolation, customer visibility, and existing booking/payment/design regression suites. Use isolated SQLite test settings, never the configured production test database.
