# Customer concerns

Customers may cancel their own New concern before an admin response or processing action. Cancellation keeps the ticket, attachments and audit history, and changes its status to Cancelled. It cannot be reopened from a stale admin update form. Admin can filter cancelled tickets and view them for reference.

The first processing action is remembered even if an admin later resets the status to New or clears the response. Migration `0110_concern_submission_and_cancellation` marks existing In Progress, Resolved and nonempty-response tickets as already handled.

Every rendered submission form has a UUID. The database permits one ticket for that user and form UUID, including retries after the short-lived shared submission receipt expires. The existing receipt lock also protects concurrent identical legacy requests without a UUID. Separate freshly opened forms can submit distinct concerns. Existing account and upload rate limits still apply.

While sending, the button is disabled and repeat submit events are ignored. If the response is lost or times out, fields, attachments and the form UUID remain available for retry. Cancellation updates the existing row without discarding a separate unsent draft.

The upload area supports browsing and drag-and-drop, with removable previews. Both the browser and server enforce up to four JPG, PNG or WEBP images, each at most 5MB. The server verifies actual image content, rather than trusting the file extension.

The page presents the reporting form beside recent concern history on desktop. History includes the subject, ticket number, category, status and submission date. On smaller screens the form appears first and the table scrolls horizontally with visible View and Cancel controls. Required labels have red asterisks; attachments are marked `(optional)`. Inputs, focus rings, validation colors, table surfaces, status badges and upload controls follow the admin concern palette in both themes. Empty required fields turn red on focus or submission, retaining the red border and focus ring until valid text is entered or a category is selected. Clearing a value or entering only whitespace restores the error; the Other field is required only for that category. The subject field shows its character count and field errors remain inline.

Submission and cancellation show the shared admin-style top-right success/error toast. A successful submission keeps its toast visible through account navigation (or restores it after a full page load). Cancellation uses the shared client confirmation styling, keeps focus on the safe action initially, and disables dismissal while the request is pending. Failed requests preserve the draft or confirmation for retry.

## Admin queue and notifications

The admin Concerns queue includes all dates by default. Its New KPI and sidebar badge both count all New tickets. The other KPIs also cover the entire history; optional date, category, status and search filters apply to table results only. Reporting presets use the current Asia/Manila date, including the hours after local midnight when the UTC date is still yesterday. This replaces the implicit 31-day cutoff that hid recent submissions and made counts disagree.

A successful customer submission creates one `AdminNotification` linked directly to the concern, inside the same transaction as the ticket. Replaying the submission UUID creates neither a second ticket nor a second notice. Migration `0114_admin_concern_notifications` adds the nullable concern relation; older booking/payment/review notifications remain supported. Existing tickets remain in the queue; old submissions are not resent as new notifications.

The admin header loads notifications on demand, with stable signed-cursor pagination across booking and event records. Opening the panel does not mark items read. Individual clicks and the explicit Mark all as read action require CSRF-protected POST requests. Unread counts exclude hidden records. A focus/30-second refresh updates the badge and concern counts; changed counts refresh the idle concern queue. Concern notices open the exact current ticket, including tickets outside the current table filters or page. Avatar, notification and theme controls share the client interaction styles, including reduced-motion support.

The queue uses asynchronous filtering and pagination (8 rows by default; Show 4/8), preserves the current list on failed requests, and provides retry actions. Detail requests always load the latest ticket state. Queue access and updates require the Admin role. Updates are asynchronous and keep notes on failure. Cancelled concerns remain read-only, with cancellation versus processing serialized by the customer-account and ticket row locks. Updates notify the customer only when the status changes. Attachments open in a separate accessible image dialog.

Saving a concern's status or customer update shows the shared top-right notification above the details modal. Failed saves show error feedback and retain the draft. The notification uses the same light/dark styling, three-second timer and dismissal as Admin Users. A failed queue refresh keeps its retry message separate from a successful save. Review Management uses this notification for feature/unfeature and reply creation, editing and removal; input validation remains beside its field.

## Deployment

Apply `python manage.py migrate --no-input` before the updated application serves requests. The Railway pre-deploy and start commands already do this. The migration was applied to the local development database during implementation. Previously submitted duplicate tickets are retained.

## Verification

Run the concern, request-protection and email regression suites against an isolated test database:

```powershell
.venv/Scripts/python.exe manage.py test app.test_concerns app.test_request_protection app.test_email_delivery app.test_toast_ui --settings=Project.test_settings
.venv/Scripts/python.exe manage.py test app.test_admin_concerns.AdminConcernTests app.test_concern_notifications.ConcernNotificationTests app.test_customer_notifications.CustomerNotificationTests app.test_notif_routing --settings=Project.test_settings
```

Use PostgreSQL to exercise concurrent row locking; the two PostgreSQL-only tests are skipped on SQLite. The opt-in `app.test_concerns_browser` suite uses installed Microsoft Edge and Playwright, isolated test accounts and mocked admin email delivery. Set `RUN_CONCERN_BROWSER=1` to run it. It commits a submission, drops the response, retries it, and verifies that one ticket and attachment remain. It also checks cancellation, preservation of an unsent draft, attachment preview, and the read-only admin view.

Set `RUN_ADMIN_CONCERNS_BROWSER=1` to run `app.test_admin_concerns.AdminConcernBrowserTests` with installed Chrome and Playwright against an isolated PostgreSQL test database. The tests cover a real customer submission, live admin badge, exact ticket link, status notification, async filtering/pagination, retries, validation, long text, attachments, cancelled tickets, keyboard controls and light/dark layouts at desktop/tablet/mobile widths.
