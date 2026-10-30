# Email through Brevo HTTPS API

All application emails use the shared Django backend `app.email_backend.BrevoEmailBackend`.
There is no SMTP connection or automatic SMTP/console fallback. An old
`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` is also mapped to Brevo,
so a stale Railway variable cannot keep using blocked SMTP ports.
No new package or database migration is required.

## Activate email on Railway

1. Create a Brevo account and complete account verification. Ensure transactional
   email is activated; an account review may be required.
2. Add and verify the email sender in Brevo. For a domain you own, publish Brevo's
   DKIM/DMARC verification records at your DNS provider. The Railway-provided
   `up.railway.app` domain is not your sending domain. Gmail recipients do not need
   their own domain. Brevo may rewrite an unauthenticated/Gmail sender to a
   `brevosend.com` address; use an authenticated domain for a branded sender.
3. Under Brevo's **SMTP & API → API Keys**, create an API key (not an SMTP key).
4. In **Railway → Django service → Variables**, set:

   ```dotenv
   EMAIL_BACKEND=app.email_backend.BrevoEmailBackend
   BREVO_API_KEY=<your-private-Brevo-API-key>
   DEFAULT_FROM_EMAIL=Balloorina <your-verified-sender@example.com>
   EMAIL_TIMEOUT=10
   ```

   Replace the examples with real values. Keep keys in environment variables,
   never in Git, screenshots, chat, or browser code. Remove the old `EMAIL_HOST`,
   `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and
   `EMAIL_FAIL_SILENTLY` variables; these are no longer used by this application.
5. Deploy these code changes and apply/redeploy the Railway variable changes.
   Changing `.env.example` alone does not configure production. For local use,
   copy the same email variables into the ignored `.env`; it was not modified by
   this change. If a local `.env` exists, this project's settings load it with
   `override=True`, so keep its email values consistent with the intended service
   configuration and do not package a development `.env` in production.
6. From the deployed service shell, run:

   ```sh
   python manage.py sendtestemail your-test-inbox@gmail.com
   ```

   This sends one real email. Check Brevo's transactional logs and the recipient's
   Inbox/Spam. API acceptance is not proof of inbox delivery.

## Covered flows

| Trigger | Recipients / existing controls |
| --- | --- |
| Sign-up and resend verification | Account email receives a 6-digit OTP; verification still required before login |
| Forgot password | Account email receives a 6-digit OTP; existing cooldown/rate limits and generic response |
| Logged-in password change | Current account email receives a 6-digit OTP before the new password is applied |
| Admin account activation / deactivation | Selected account's email; confirmation required; status and audit entry roll back if email cannot be sent |
| New booking | Admin addresses in Site Settings, when email notifications are enabled |
| Payment proof submitted | Admin addresses in Site Settings, when enabled |
| Concern ticket submitted | Admin addresses in Site Settings, when enabled |
| PayMongo payment received | Configured admin addresses; webhook and browser return share one notification flag, so retries do not duplicate alerts |
| Customer change request, new review, admin support request | Configured admin addresses, when enabled |
| Booking deadline alert | Configured admin addresses; the existing unique deadline notice prevents duplicates |
| Payment reminder | Booking customer's email; existing reminder cooldown |
| Admin sends a paid booking's design | Booking customer's email; design file attached with order number and admin message (or default); after commit, with submission replay protection |
| Support reply to an offline customer | Customer's email; chat/in-app notification survives email failure |
| Policy update with Notify Clients selected | Individual active customer emails; recipient privacy preserved |

**Site Settings → Email Notifications** controls admin activity alerts, including booking/payment/concern, change requests, reviews, support requests and deadline notices. Keep it enabled and supply valid comma-separated admin addresses to
receive those alerts. Customer policy-update notices use the separate **Email active customers about this update** checkbox in the policy editor. They send only for actual content changes, one email per active customer address, and report delivery failures without losing the saved policy.

## Failures, quota, and verification

The free quota is shared by all emails and all recipients, including resends,
reminders, and policy notices. Brevo currently documents 300 sends/day; after the
daily quota, transactional emails can be queued by Brevo rather than delivered
immediately. Monitor credits, transactional activation, delivery logs, spam, and
sender authentication in Brevo.

The backend requires HTTP 201 with a message ID before reporting success. HTTP
errors, timeouts, and malformed responses are failures. It uses a bounded timeout
and no automatic retries, to avoid duplicate messages when acceptance is unclear.
Logs exclude API keys, raw API response bodies, and email bodies. Non-critical
email failures do not roll back bookings, payments, concerns, policy saves, or chat.
Payment reminder audit logs record email failure separately from in-app success.
Design delivery emails use the validated original image bytes as an attachment,
without fetching a public storage URL. The order number is the booking ID. A blank
admin message uses standard text. The admin's send result reports provider acceptance
or an unconfirmed email attempt; email failure never removes the saved design or
customer's in-app notification. No email is sent for a rolled-back upload, and
replaying the same submission ID does not send a duplicate. There are no automatic
retries; check Brevo delivery logs before attempting another send.
Sign-up retains its existing behavior of removing an account when verification
email submission fails, so retrying registration is possible. Forgot-password and
resend responses stay generic to avoid exposing whether an account exists.

## Signup, recovery and password change OTPs

Create-account verification, self-service forgot password, and logged-in password changes use email OTPs.
Normal customer/admin login and booking/payment emails keep their existing behavior.
Admin-requested password-reset links keep their existing flow.

- Signup opens `/verify-account/`; users enter the code before they can log in.
  A fresh login page has no verification shortcut. After a signup in this browser,
  or a login with correct credentials for an unverified account, an inline banner
  shows the masked recipient and **Continue Verification**. Login remains blocked
  until verification succeeds. The login email is prefilled; the password is cleared.
- Continue is a CSRF-protected POST using the account already authorized in the
  server session; posted email values cannot select an account. It reuses a bound
  code without another email, or explicitly requests one when no bound challenge
  remains. Expired codes can be resent on the OTP page. A cooldown or provider failure
  stays on the prefilled login page with a clear message.
- The browser remembers one pending account at a time. **Use another account**
  clears only its signup state, preserving accounts and their records. A different
  browser must supply login credentials first. Verification, password/email changes,
  deactivation and signup expiry invalidate stale continuation state.
- Public duplicate-email and duplicate-username signup submissions use the same
  generic OTP redirect and notice as a valid new signup. They do not overwrite an
  existing account. Only a browser already authorized for that account sees its
  pending banner. Public email-only resend requests do not create private banners.
  Invalid/expired legacy links never prefill or disclose a user's email.
- **Change email address** on signup requires the original signup password. A new
  code is sent to the replacement Gmail; the account email changes only after that
  code is verified. Usernames, profile details and passwords are preserved. The
  address is checked again under a database lock before being committed. Five
  password guesses per account in 10 minutes apply across sessions and IPs.
- Logged-in **Change Password** first validates the current password, matching new
  passwords, and existing password rules. `/verify-password-change/` then requires
  an OTP in the same authenticated browser. Only a password hash is staged in the
  database; submitting the profile form never changes the password immediately.
  Correct verification changes it once, invalidates recovery and change challenges,
  preserves the current session and returns to the appropriate customer/admin
  profile. Cancel, expiry and email failure leave the current password intact.
- All OTP pages have six accessible digit inputs, full-code paste/mobile autofill,
  keyboard navigation, inline feedback, expiry and resend countdowns. The server
  also accepts the six named fields without JavaScript.
- Forgot password opens `/forgot-password/verify/`. A correct code authorizes
  `/forgot-password/reset/` in that same browser for 10 minutes. The user must
  explicitly log in after changing the password; recovery does not verify an
  unverified account.
- Codes are six digits, including leading zeros, and expire after 10 minutes.
  The database stores a keyed digest, account/email/password snapshot, browser
  binding, and lifecycle timestamps; raw codes are never persisted or logged.
- Five wrong submissions per account/purpose and email/purpose in 10 minutes lock further attempts
  until the window ends. Resending, opening another session, or changing IP cannot
  clear this account budget. The IP budget is 30 submissions per 10 minutes.
  These OTP budgets remain enabled even if general request limiting is disabled.
- Resends wait 60 seconds per email/purpose and per IP and share existing hourly
  send limits. Accepted resends invalidate previous challenges and reset grants.
  If sending fails, the previous accepted code remains usable in its original browser.
- A verified reset code is erased and exchanged for a browser-bound, single-use
  reset authorization. Password/email changes, deactivation, expiry, or completing
  a password reset make old authorizations unusable.
- Existing verification links remain valid until their original expiry; they now
  open a confirmation form whose POST verifies the email (GET does not modify the
  account). Existing password-reset links still work. Completing either legacy
  flow invalidates OTP challenges for that purpose.

Optional environment settings (defaults already apply without adding variables):

```dotenv
EMAIL_OTP_TIMEOUT=600
EMAIL_OTP_RESET_TIMEOUT=600
EMAIL_OTP_MAX_ATTEMPTS=5
EMAIL_OTP_ATTEMPT_WINDOW=600
EMAIL_OTP_VERIFY_PER_IP=30
PENDING_SIGNUP_RETENTION_DAYS=7
PENDING_SIGNUP_CLEANUP_ENABLED=True
PENDING_SIGNUP_CLEANUP_INTERVAL_SECONDS=3600
PENDING_SIGNUP_CLEANUP_BATCH_SIZE=500
PASSWORD_CHANGE_OTP_COOLDOWN_SECONDS=60
PASSWORD_CHANGE_OTP_RATE_LIMIT_PER_EMAIL=3
PASSWORD_CHANGE_OTP_RATE_LIMIT_PER_IP=5
PASSWORD_CHANGE_OTP_RATE_LIMIT_WINDOW_SECONDS=3600
```

The existing `FORGOT_PASSWORD_*` and `VERIFICATION_RESEND_*` variables control
sending cooldowns and hourly limits for recovery and signup. `PASSWORD_CHANGE_OTP_*`
controls authenticated password-change email sending. `PASSWORD_RESET_TIMEOUT` and
`EMAIL_VERIFICATION_TIMEOUT` now apply to legacy links, not OTPs.

Apply migrations through `0109_pending_signup_expiry` before serving the new code. Railway's
existing pre-deploy/start migration commands already do this. For a manual
deployment, run `python manage.py migrate --noinput` before starting the app.
Existing users need no data backfill or repeat verification.

New website signups have a fixed seven-day verification window, separate from
an OTP's ten-minute lifetime. Resending does not extend the signup window. Migration
0109 leaves every existing account's retention marker null; it never opts legacy
users into deletion. Successful OTP or legacy verification clears that marker.

The existing deadline worker runs bounded cleanup in development/Gunicorn, with a
shared database budget so replicas run at most one batch per interval. It only
removes marked, expired, active customer signups that have never logged in and have
no other activity. Admin/superusers, disabled users, groups/permissions, and
all related records (bookings, payments, audit logs, chat, designs, etc.) protect the
account. OTP challenges alone do not count as activity and are removed with an
eligible abandoned signup. Accounts with activity are retained and removed from
the abandoned-signup cleanup policy. Expired unused email/username reservations can
also be reclaimed during a valid registration POST, without waiting for the worker.
`PENDING_SIGNUP_CLEANUP_ENABLED=False` disables both automatic paths; manual cleanup
remains an explicit operation. Input length/format validation happens before account
conflict handling, including for requests that bypass browser validation.

For an operational preview, then an optional manual batch:

```sh
python manage.py prune_pending_signups --dry-run --limit 500
python manage.py prune_pending_signups --limit 500
```

These commands target the configured database. Run them only against the intended
environment. No existing account data is deleted by applying the migration.

After deployment, use a controlled test account to check signup → resend → OTP →
login, leaving signup and continuing it, changing a pending signup email,
logged-in password change with OTP, and forgot password → OTP → password update → login. Confirm acceptance
and delivery in Brevo and test an expired code plus one old link. Do not log codes
or include real API keys in diagnostics. The isolated suites below do not send
real emails; live inbox delivery must be verified against the deployed service.

Run isolated tests without contacting Brevo or the configured production database:

```sh
python manage.py test app.test_email_otp app.test_otp_account_flows app.test_signup_privacy app.test_signup_cleanup app.test_email_backend app.test_email_delivery app.test_email_verification app.test_policy_notify app.test_request_protection --settings=Project.test_settings
```

`EmailOTPConcurrencyTests` requires an isolated PostgreSQL test database for real
row-lock verification; SQLite skips those cases. Never point test creation at the
production database. The optional browser checks use installed Edge, the existing development
environment with Playwright available, and an isolated live test server (`RUN_EMAIL_OTP_BROWSER=1`, then run
`app.test_email_otp_browser` with `Project.test_settings`). It exercises the code
boxes, paste/autofill, keyboard navigation, resend countdown, CSRF-protected submission,
both themes, signup continuation, signup email replacement, recovery, and
authenticated password change. They cover narrow mobile and desktop layouts.

References: [Brevo API](https://developers.brevo.com/reference/send-transac-email),
[sender authentication](https://help.brevo.com/hc/en-us/articles/16045394674066-Troubleshooting-Domain-authentication),
[free plan limits](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan).
