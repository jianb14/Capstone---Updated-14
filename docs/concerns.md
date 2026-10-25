# Customer concerns

Customers may cancel their own New concern before an admin response or processing action. Cancellation keeps the ticket, attachments and audit history, and changes its status to Cancelled. It cannot be reopened from a stale admin update form. Staff can filter cancelled tickets and view them for reference.

The first processing action is remembered even if an admin later resets the status to New or clears the response. Migration `0110_concern_submission_and_cancellation` marks existing In Progress, Resolved and nonempty-response tickets as already handled.

Every rendered submission form has a UUID. The database permits one ticket for that user and form UUID, including retries after the short-lived shared submission receipt expires. The existing receipt lock also protects concurrent identical legacy requests without a UUID. Separate freshly opened forms can submit distinct concerns. Existing account and upload rate limits still apply.

While sending, the button is disabled and repeat submit events are ignored. If the response is lost or times out, fields, attachments and the form UUID remain available for retry. Cancellation updates the existing row without discarding a separate unsent draft.

The upload area supports browsing and drag-and-drop, with removable previews. Both the browser and server enforce up to four JPG, PNG or WEBP images, each at most 5MB. The server verifies actual image content, rather than trusting the file extension.

The page presents the reporting form beside recent concern history on desktop. History includes the subject, ticket number, category, status and submission date. On smaller screens the form appears first and history rows become compact cards with visible View and Cancel controls. The subject field shows its character count; field errors and submission feedback remain inline.

## Deployment

Apply `python manage.py migrate --no-input` before the updated application serves requests. The Railway pre-deploy and start commands already do this. The migration was applied to the local development database during implementation. Previously submitted duplicate tickets are retained.

## Verification

Run the concern, request-protection and email regression suites against an isolated test database:

```powershell
.venv/Scripts/python.exe manage.py test app.test_concerns app.test_request_protection app.test_email_delivery app.test_toast_ui --settings=Project.test_settings
```

Use PostgreSQL to exercise concurrent row locking; the two PostgreSQL-only tests are skipped on SQLite. The opt-in `app.test_concerns_browser` suite uses installed Microsoft Edge and Playwright, isolated test accounts and mocked admin email delivery. Set `RUN_CONCERN_BROWSER=1` to run it. It commits a submission, drops the response, retries it, and verifies that one ticket and attachment remain. It also checks cancellation, preservation of an unsent draft, attachment preview, and the read-only admin view.
