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
| Sign-up and resend verification | Account email; verification still required before login |
| Forgot password | Account email; existing cooldown/rate limits and generic response |
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

Run isolated tests without contacting Brevo or the configured production database:

```sh
python manage.py test app.test_email_backend app.test_email_delivery app.test_email_verification app.test_policy_notify app.test_request_protection --settings=Project.test_settings
```

References: [Brevo API](https://developers.brevo.com/reference/send-transac-email),
[sender authentication](https://help.brevo.com/hc/en-us/articles/16045394674066-Troubleshooting-Domain-authentication),
[free plan limits](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan).
