# Customer account pages

Profile, bookings, payments, reviews and concerns extend `client/account_base.html`.
The shared sidebar stays in place while `account_navigation.js` fetches and replaces
`#accountContent`. Sidebar URLs come from Django's rendered links. Direct visits,
refresh, modified clicks and public-site links continue to work normally.

At widths of 968px and below, the sidebar is hidden and the avatar menu contains
all account destinations. Desktop keeps the sidebar and a compact avatar menu.
There is no separate account dropdown above the page content. Both menus update
the active item after asynchronous navigation and browser history changes.

Navigation loads the destination's styles and scripts before replacing the current
page. Page styles are removed on leaving; external scripts are loaded once.
Inline initialization is registered again with the destination's fresh template data.
History entries support Back and Forward. A failed request keeps the current content
and offers a retry.

## Page initialization

Use `AccountPages.register(pageName, key, factory, priority)` for account-only
initializers. `AccountPages.enhance` also supports shared modules used on public or
admin pages. Smaller priorities run first, then `scope.ready` callbacks run after
all factories. This replaces document-ready callbacks for content that can mount
more than once.

- Keep page variables inside the factory.
- Use `scope.expose` for functions required by inline HTML handlers.
- Use `scope.capture` before assigning other page-specific window properties.
- Use `AccountPages.listen` for document/window listeners so they are removed
  when leaving the page.
- Register observer, map, timer and request cleanup with `scope.cleanup`.
- Check `scope.active` before processing responses that may arrive after leaving.

Reviews retain their own asynchronous create, edit, delete, likes and pagination.
Profile, pending-booking edits/deletions, booking reviews and quote acceptance/
withdrawal submit JSON through `account_forms.js`. Existing server validation and
ordinary HTML form fallbacks remain available. Errors keep the current form and
entered data. Successful saves refresh the workspace without a new document.
Password changes use an inline email-code dialog, including resend and throttling,
and keep the authenticated session after verification. Persistent navbar and chat
widgets are initialized once. Payments keep their existing checkout flow.
Profile account removal has its own asynchronous, session-bound verification and
final confirmation flow; see [account-deletion.md](account-deletion.md).

## Tables and visual styles

`account_ui.css` owns the common heading, subtitle, KPI, dropdown, table, empty
state and pagination styles. Titles follow the Report Concern heading. Logout
keeps its red foreground on hover in both themes. `account_motion.js` provides
480ms entrances for account sections and replaced table results; reviews keep
their existing motion module. Both honor reduced motion and clean up on navigation.

Bookings, all three payment tabs and concern history default to eight rows.
The Show selector supports four or eight, with the same server-side upper limit.
Concern history is no longer restricted to the most recent twenty tickets.
Tables remain tables on mobile and scroll within their own region.

`account_tables.js` updates only the list fragment, preserving booking modal
handlers and unfinished concern forms. Search, clear, sorting, filters, page size,
payment tabs and numbered pagination work asynchronously and support browser
history. Failed requests retain existing rows and provide a retry. All data stays
scoped to the signed-in customer.
Internal links between account pages, including payment history links inside a
booking dialog, use the same account navigation. Sidebar/profile initials share
the navbar avatar font. KPI icons use the shared SVG component; table actions
align left and payment status badges have consistent dimensions.

## Customer notifications

The navbar's `customer_notifications.js` refreshes its owner-scoped feed when
opened and loads earlier items with a signed date/ID cursor. Opening the bell
does not change read state. Individual clicks and Mark all as read persist via
CSRF-protected POST; unread indicators update only after success. Failures retain
the list and allow a retry. Notification and avatar popovers close each other,
stay inside the viewport, and support keyboard navigation and Escape.

Expired and denied bookings open booking details. Payment notices open an
existing payment's details on its actual page; newer payments do not replace
the record attached to an older notice. Current balance reminders locate the
matching actionable booking, or fall back to its details when no payment action
remains. These account links use the existing asynchronous page navigation.

Concern status changes create an unread notification in the same transaction as
the admin update. Saving the same status, editing notes alone, or rejecting an
invalid update creates no duplicate notice. Concern notifications reference the
ticket directly; migration `0113_concern_status_notifications` adds that target
and enforces exactly one booking or concern per notification. Apply migrations
before serving the updated application.

Concern links select the correct history page and open its details, with the
latest response and owner checks. The navbar checks its unread count every
30 seconds while visible and on returning to the tab, without reloading the page.

## Verification

`app.test_account_workspace` checks the shared server-rendered layout. Enable
`RUN_ACCOUNT_WORKSPACE_BROWSER=1` for integration coverage of navigation, repeated
mounts, history, cancellation, failures, review submission, booking search and maps,
and responsive layouts in both themes. Use `Project.test_settings` so verification
uses the isolated test database and mail backend.

`app.test_account_tables` covers limits, sorting, owner isolation, empty states,
payment actions and older concerns. Set `RUN_ACCOUNT_TABLES_BROWSER=1` for the
browser flow, keyboard-capable dropdowns, history, heading metrics, motion and
320px/390px/desktop screenshots in both themes. Its SQLite live server serializes
requests because Django shares one in-memory connection; PostgreSQL exercises
the normal threaded server against an isolated test database.

`app.test_account_mutations` covers JSON validation, ownership/CSRF, edits, delete,
quote actions and inline password OTP. The account-table browser suite also saves
profiles, edits/deletes a pending booking, submits a review, withdraws a proposal,
verifies a password code and follows a booking's payment-history link while
asserting a single document request. No real customer accounts or email transport
are used by these tests.

`app.test_customer_notifications` checks read ownership/CSRF, cursor pagination,
notification routing and payment page selection. Set
`RUN_CUSTOMER_NOTIFICATIONS_BROWSER=1` for click navigation, read/mark-all retries,
delayed feed responses, popover positioning, and both themes on mobile/desktop.
`app.test_concern_notifications` covers status deduplication, rollback, ownership,
older ticket links and concurrent updates. Set `RUN_CONCERN_NOTIFICATIONS_BROWSER=1`
for the admin-update-to-customer-badge and concern-dialog flow.
