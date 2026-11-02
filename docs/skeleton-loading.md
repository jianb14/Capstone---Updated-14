# Skeleton loading

The shared loader covers explicit content requests in the application admin,
customer pages and widgets. Public/auth pages that already have server-rendered
content show it immediately. The built-in Django admin, emails, exports and
external payment checkout are outside this UI.

## Behavior and integration

- There is no automatic page mask, destination layout guessed from a URL, or
  initial DOMContentLoaded mask. Home keeps its actual centered hero and buttons.
  The existing page-boundary attributes are metadata, not automatic triggers.
- Account navigation retains the current page and sidebar until its replacement
  is ready. A small status notice appears after 180ms without moving the page.
- Explicit requests wait 180ms before showing placeholders. Completing/aborting
  before that cancels the display. There is no minimum display time and no
  additional wait before rendering a successful result.
- Placeholders follow the measured text, images, fields and media in the actual
  region. Existing table columns, card grids, spacing and responsive layouts remain
  in place. Headers, filters, pagination, populated inputs and controls remain
  readable. Protected control areas are cut out of media placeholders.
- A first-time empty panel has no record/form layout to copy. It gets one compact
  loading line beside the empty region, rather than invented fields or cards.
- The layer is rendered in a portal outside the content region. Native dialog and
  popover layers host their own portal. Scrolling, clipping, resizing and finite
  entrance animations keep it aligned. No content children, dimensions, visibility
  or positioning styles are overwritten.
- This boundary is essential for FullCalendar, Fabric and Leaflet: their mount DOM
  belongs to the library. A loader must never be inserted into that managed DOM.
  Removing a loader must not remove a library element adopted during rendering.
- Append mode copies the layout of the last loaded entry into a temporary sibling
  slot. Existing entries remain visible. Closing/unmounting a region, abort,
  Back/Forward restoration and the 30-second fail-safe clean up owned nodes.
- Background polling keeps content visible. AI generation retains real progress
  and streamed output instead of adding a speculative response layout.
- Content images shimmer only if still pending after 180ms, using their existing
  CSS/HTML dimensions. The loader does not assign an arbitrary aspect ratio.
  Cached/error sources clean up immediately; decorative imagery and navigation
  branding stay visible.
- Placeholders are aria-hidden. The request region has aria-busy and a separate
  accessible status. Reduced motion disables shimmer. Without JavaScript the
  server-rendered content remains visible.

~~~js
const loading = window.SiteLoading?.start(results, {
    variant: 'table',                 // semantic hint, not a generic HTML layout
    label: 'Loading bookings...',
    mode: 'replace',                  // append keeps loaded rows/messages visible
    signal: controller.signal,
});
try {
    // Fetch, verify this request is current, render and initialize controls.
} finally {
    loading?.finish();               // idempotent; stale handles cannot clear newer ones
}
~~~

SiteLoading.clear(root) releases requests below a closing/unmounting root.
SiteLoading.scan(root) checks newly inserted images. It does not mask a page.
The delay override exists for exceptional integrations and deterministic tests;
ordinary application requests use the 180ms default.

## Coverage

| Area | Pending content |
| --- | --- |
| Dashboard, analytics, AI health | Report results, actual charts/media, request history and summary |
| Admin queues | Bookings/change requests, payments, users, reviews, concerns and audit results |
| Admin catalog/content | Shared catalog rows, fetched detail/editor bodies, gallery and canvas filters |
| Admin settings/security | Fetched payment settings, invitation directory and resumed challenge state |
| Customer account | Shared list filtering/pagination, booking/event-design dialogs, fetched password/deletion state |
| Public content | Review filtering, AI theme/availability results, content images and previews |
| Booking/design | Calendar state refresh, place results, reverse lookup, maps, design search and canvas restoration/assets |
| Notifications/support | Feed opening/history, conversation search/history/media and inbox results |
| AI chat | Session/history requests; real status and streaming progress during generation |
| Public/auth navigation | Ready content remains visible; no synthetic full-page loading layout |

## Verification

Use isolated SQLite settings, not the configured production test database:

~~~powershell
.\.venv\Scripts\python.exe manage.py test app.test_skeleton_loading app.test_account_workspace app.test_account_tables app.test_admin_navigation app.test_customer_booking_modals app.test_admin_catalog app.test_admin_booking_workspace --settings=Project.test_settings --noinput
$env:RUN_SKELETON_BROWSER = '1'
.\.venv\Scripts\python.exe manage.py test app.test_skeleton_loading_browser --settings=Project.test_settings --noinput
~~~

The opt-in Edge suite checks:

- Actual media/placeholder coordinates and unchanged content dimensions at
  390px, 768px and 1440px in light/dark themes, plus reduced motion and no JavaScript.
- Fast-request suppression, source changes/cache/errors, request ownership, abort,
  DOM replacement, timeout and closing a pending native dialog.
- Real FullCalendar 6.1.11, including the original mount-adoption regression,
  first Month render, reload, navigation and Month/Week switching. Booking's
  actual first Month grid is checked in all six size/theme combinations.
- Ready Home/account content, delayed account navigation, browser Back and native
  navigation without full-page masks.
- Actual admin columns, preserved headers/filters, retry and dialog closure.
- Notification/chat initial requests and unobscured background polling.

The existing catalog, booking, gallery, auth, account, calendar and canvas browser
suites provide broader interaction regression checks. Screenshots and the cached
FullCalendar test bundle live in ignored .booking-followup-check/.
