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
| Admin-initiated password reset | Selected user's email |
| New booking | Admin addresses in Site Settings, when email notifications are enabled |
| Payment proof submitted | Admin addresses in Site Settings, when enabled |
| Concern ticket submitted | Admin addresses in Site Settings, when enabled |
| Payment reminder | Booking customer's email; existing reminder cooldown |
| Support reply to an offline customer | Customer's email; chat/in-app notification survives email failure |
| Policy update with Notify Clients selected | Individual active customer emails; recipient privacy preserved |

**Site Settings → Email Notifications** controls booking/payment/concern admin
alerts only. Keep it enabled and supply valid comma-separated admin addresses to
receive those alerts. This change preserves existing email triggers; it does not
add new booking-status or receipt emails where none previously existed.

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
Sign-up retains its existing behavior of removing an account when verification
email submission fails, so retrying registration is possible. Forgot-password and
resend responses stay generic to avoid exposing whether an account exists.

## Signup and self-service recovery OTPs

Only create-account verification and self-service forgot password use email OTPs.
Normal customer/admin login, booking/payment emails, and logged-in password changes
do not require an OTP. Admin-requested password-reset links keep their existing flow.

- Signup opens `/verify-account/`; users enter the code before they can log in.
- Forgot password opens `/forgot-password/verify/`. A correct code authorizes
  `/forgot-password/reset/` in that same browser for 10 minutes. The user must
  explicitly log in after changing the password; recovery does not verify an
  unverified account.
- Codes are six digits, including leading zeros, and expire after 10 minutes.
  The database stores a keyed digest, account/email/password snapshot, browser
  binding, and lifecycle timestamps; raw codes are never persisted or logged.
- Five wrong submissions per email/purpose in 10 minutes lock further attempts
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
```

The existing `FORGOT_PASSWORD_*` and `VERIFICATION_RESEND_*` variables control
sending cooldowns and hourly limits. `PASSWORD_RESET_TIMEOUT` and
`EMAIL_VERIFICATION_TIMEOUT` now apply to legacy links, not OTPs.

Apply migration `0107_emailotpchallenge` before serving the new code. Railway's
existing pre-deploy/start migration commands already do this. For a manual
deployment, run `python manage.py migrate --noinput` before starting the app.
Existing users need no data backfill or repeat verification.

After deployment, use a controlled test account to check signup → resend → OTP →
login, and forgot password → OTP → password update → login. Confirm acceptance
and delivery in Brevo and test an expired code plus one old link. Do not log codes
or include real API keys in diagnostics. The isolated suites below do not send
real emails; live inbox delivery must be verified against the deployed service.

Run isolated tests without contacting Brevo or the configured production database:

```sh
python manage.py test app.test_email_otp app.test_email_backend app.test_email_delivery app.test_email_verification app.test_policy_notify app.test_request_protection --settings=Project.test_settings
```

`EmailOTPConcurrencyTests` requires an isolated PostgreSQL test database for real
row-lock verification; SQLite skips those cases. Never point test creation at the
production database. The optional mobile browser check uses installed Edge and
an isolated live test server (`RUN_EMAIL_OTP_BROWSER=1`, then run
`app.test_email_otp_browser` with `Project.test_settings`). It exercises the code
field, resend countdown, CSRF-protected submission, both themes, and password reset.

References: [Brevo API](https://developers.brevo.com/reference/send-transac-email),
[sender authentication](https://help.brevo.com/hc/en-us/articles/16045394674066-Troubleshooting-Domain-authentication),
[free plan limits](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan).
