# Request protection

The middleware in `app/request_limits.py` reserves shared request budgets in
`RequestRateBucket`. Counters use the application's database, so all workers using
that database enforce the same limits; Redis is not required. Keys are HMAC hashes
of policy and account/IP/email identities. Raw identities and request bodies are
not stored in the counter table.

## Default budgets

Budgets count attempts, including invalid forms and repeated submissions. Each
window starts with the first reserved request and resets when it expires.
Rejected requests do not extend the window. When a request needs several budgets,
all are reserved in one transaction or none are consumed.

| Policy | Default | Identity / coverage |
| --- | --- | --- |
| `login_account` | 10 / 15 minutes | Normalized email on application login; username on Django admin login; successful login clears this counter |
| `login_ip` | 60 / 15 minutes | IP, shared by application and Django admin login; not cleared by successful login |
| `registration` | 10 / hour | IP; includes initial verification email |
| `password_reset_submit` | 10 / 15 minutes | IP; reset-token form submissions |
| `password_change` | 10 / 15 minutes | Account |
| `booking_create` | 5 / 10 minutes | Account |
| `booking_daily` | 20 / 24 hours | Account; same creation requests |
| `booking_change` | 10 / 10 minutes | Account; pending-booking edits and amendment requests |
| `payment_submit` | 5 / 10 minutes | Account; shared by manual proof, PayMongo checkout, and amendment payment |
| `chat_send` | 30 / minute | Account; chat API and staff thread replies |
| `support_request` | 5 / 10 minutes | Account; request a human agent |
| `concern` | 5 / hour | Account |
| `review_submit` | 5 / hour | Account |
| `review_edit` | 20 / hour | Account |
| `reaction` | 30 / minute | Account; review likes and support chat reactions |
| `design_save` | 30 / 10 minutes | Account; design library and chat design saves |
| `upload_requests` | 20 / minute | Account; multipart uploads, including staff uploads |
| `upload_bytes` | 128 MiB / 24 hours | Account; combined multipart file sizes |
| `report_export` | 10 / 10 minutes | Account; Excel and PDF analytics exports share a budget |
| `receipt_download` | 20 / 10 minutes | Account; payment receipt PDF generation |

Forgot-password and verification-resend forms retain their existing separate
settings: 60 seconds between requests per IP, 5 requests per IP per hour, and
3 per normalized email per hour. These counters now also use the shared database.
Unknown emails receive the same budget treatment as existing accounts.

Read-only pages, chat polling/presence/typing, and payment provider callbacks are
outside these route budgets. AI requests also use shared counters; see
[AI assistant configuration](ai-assistant.md) for the AI policies and saved queue.
Anonymous requests to account-only routes retain normal authentication handling.

## Responses and configuration

Blocked requests return HTTP 429 with `Retry-After` in seconds and
`Cache-Control: no-store`. API, AJAX, and JSON requests receive JSON with `success`,
`error`, `message`, and `retry_after`. Ordinary forms receive an English error
page compatible with light and dark themes; email forms keep their own messages.
If the shared counter store is unavailable, protected requests fail closed with
HTTP 503 and a short retry interval.

Every policy supports environment overrides named
`RATE_LIMIT_<UPPERCASE_POLICY>_COUNT` and
`RATE_LIMIT_<UPPERCASE_POLICY>_WINDOW_SECONDS`. For example:

```dotenv
RATE_LIMIT_PAYMENT_SUBMIT_COUNT=5
RATE_LIMIT_PAYMENT_SUBMIT_WINDOW_SECONDS=600
```

A count of zero disables that individual policy. `REQUEST_RATE_LIMITING_ENABLED`
defaults to `True`; disabling it also disables email budgets and multipart size
protection, but leaves submission deduplication active.

`UPLOAD_MAX_REQUEST_BYTES` defaults to 33,554,432 bytes (32 MiB) for a complete
multipart POST. Oversized requests with a declared `Content-Length` are rejected
with HTTP 413 before upload parsing by CSRF/the view. Existing per-field file
validation still applies. Configure the reverse proxy's maximum body size too,
to bound upload bandwidth and requests without a trustworthy content length.
The upload byte budget covers multipart files, not base64 image fields in JSON.

Client IPs come from `REMOTE_ADDR`. `X-Forwarded-For` is accepted only when the
direct peer belongs to `RATE_LIMIT_TRUSTED_PROXY_CIDRS`, a comma-separated list
of the deployment's actual proxy networks. The chain is checked from the right,
stopping at the first untrusted address. Configure this for a reverse-proxy
deployment so customers do not share the proxy's IP budget. Never trust arbitrary
public clients or use `0.0.0.0/0` / `::/0` as trusted proxy networks.

## Repeat submissions

Successful booking creation, amendment requests, and payment submissions have
short-lived `SubmissionReceipt` records. Matching POSTs from the same customer to
the same path replay the original success response for `SUBMISSION_REPLAY_SECONDS`
(default 120). File contents are hashed and rewound before the view runs; CSRF
tokens are excluded from the fingerprint. AJAX/HTML switches cannot create a
second booking. Validation errors are not cached.

The receipt lock and database writes share a transaction. Payment creation also
locks its booking before checking pending payments; different payloads cannot
both pass that check concurrently. PostgreSQL provides these row locks in
production; SQLite may reject simultaneous writes with a database-lock error.
This protects ordinary retries/double clicks, but it does not guarantee exactly
one external provider operation across a server crash after provider success and
before the database commits. Existing payment reconciliation and webhook handling
remain necessary.

## Deployment and maintenance

Apply the additive migration before starting workers with this middleware:

```shell
python manage.py migrate
```

Expired records are reused automatically when the same identity submits again.
To remove old identities and stored short-lived response bodies, schedule this
command daily using the deployment scheduler:

```shell
python manage.py prune_request_protection
```

Run isolated regression tests without touching the configured production database:

```shell
python manage.py test app.test_request_protection app.test_email_verification --settings=Project.test_settings
```
