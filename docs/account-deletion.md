# Customer account removal

Apply `python manage.py migrate` before serving the updated application. Migration
0112 adds `User.deleted_at`, the media removal retry queue and the deletion OTP
purpose. It does not delete existing accounts or transactions.

My Profile provides a compact overview, editable personal information, password
security, activity and a separate Delete account section. Deletion uses the same
accessible dialog and password visibility controls as the other profile forms.
It works when opening the page directly or navigating within the account workspace.

## Eligibility and verification

Only the authenticated, verified customer can remove their account. Administrator accounts are excluded. Pending, approved, upcoming and cancellation
requested bookings block deletion even when fully paid. Completed bookings must
have no remaining balance, calculated from verified payments actually applied to
that booking. Pending payments/open checkouts, unapplied verified payments and
active booking changes also block deletion. Cancelled/expired quotations do not
create a debt by themselves; proven abandoned unpaid checkouts are ignored.

The customer confirms their current password, receives a six digit email code,
verifies it, then explicitly acknowledges permanent deletion and confirms. Code
verification alone never deletes the account. Codes are hashed, single use,
session/email/password bound, expire after `EMAIL_OTP_TIMEOUT` (default 10 minutes)
and use the shared OTP guess limits. The final grant lasts
`EMAIL_OTP_RESET_TIMEOUT` (default 10 minutes). All eligibility checks run again
inside the final transaction.

`ACCOUNT_DELETION_OTP_COOLDOWN_SECONDS` defaults to 60;
`ACCOUNT_DELETION_OTP_RATE_LIMIT_PER_IP` to 5 and
`ACCOUNT_DELETION_OTP_RATE_LIMIT_PER_EMAIL` to 3 within
`ACCOUNT_DELETION_OTP_RATE_LIMIT_WINDOW_SECONDS` (3600 by default).
Current password attempts are separately limited. A failed email send leaves the
account and an older usable code intact, and still consumes the send budget.

## Retained data and cleanup

The customer login is permanently disabled with an unusable password and replaced
contact details. Existing sessions can no longer authenticate, including other
devices. The user row remains as an anonymous transaction owner named
**Deleted customer** so booking/payment relationships remain intact. The ordinary
admin customer list and edit/reset/activation/deletion actions exclude this row;
admin can inspect its retained transaction history.

Reviews/photos, saved designs, AI requests/artifacts/feedback, conversations,
concerns, notifications and customer activity are removed. Booking contact/location
and free text, design references, change snapshots, status notes and payment contact
details/receipts are cleared. Booking/payment amounts, dates, status and provider
transaction identifiers remain for reconciliation. This feature does not establish
a legal retention period or erase third party provider records or existing backups.

Database changes are atomic. Customer writes lock the user before modifying data,
so an already authenticated request cannot recreate content after removal. Admin
account edits also lock this row to prevent restoring stale profile data.
Physical file removal occurs after commit; storage failures remain in
`AccountMediaRemoval` for retry. Files still referenced by another record are
protected. The existing booking deadline worker retries cleanup every minute.
Installations without that worker should schedule:

```sh
python manage.py purge_removed_account_media --limit 100
```

## Verification

Use isolated accounts, SQLite test storage and the local mail backend:

```sh
python manage.py test app.test_account_deletion app.test_otp_account_flows app.test_email_otp app.test_profile_validation --settings=Project.test_settings
```

Set `RUN_PROFILE_BROWSER=1` to run `app.test_profile_deletion_browser` and
`app.test_profile_dialogs_browser` against the isolated browser test server.
These exercise both themes, narrow mobile/landscape and desktop, blockers,
password validation, code verification, acknowledgement and final sign out.
They also cover closing/reopening during a pending request, cleared password
visibility, restored page scrolling, and recovery after a temporary server error.
No real customer accounts or real email delivery are used by these tests.

`app.test_account_deletion_concurrency` requires an isolated PostgreSQL test
database. It checks removal against a previously authenticated write, a newly
committed booking, and a late AI completion. SQLite skips these row lock cases.
