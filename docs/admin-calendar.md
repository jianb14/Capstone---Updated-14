# Admin calendar

The calendar uses the same workspace styles and input focus ring as Admin Concerns. Month/week navigation, the month/year picker, status filters, date details and existing booking data remain available. Light/dark themes and narrow screens share the same controls.

Blocking, unblocking and refreshing now use asynchronous requests. Updates preserve the selected month/week and status filter. Successful changes show the shared admin feedback notification; validation appears below the corresponding field. Controls prevent repeated submissions while an update is in progress.

The active blocked-date list contains today and future dates. A date remains blocked for its entire day in `Asia/Manila` and moves to the read-only **View past blocked dates** history at the next midnight. This is date-based archiving: records are not deleted, and past blocked days remain marked when browsing earlier calendar months. No scheduled database cleanup is needed. An open page refreshes asynchronously at the server's next Philippine midnight, or on return to the tab after midnight; failed background updates retry after a minute. Refreshing or reopening the page uses the same server-side date boundary.

Empty blocked calendar days center their blocked icon and label; days with bookings keep those bookings visible. The blocked-date key under Booking statuses is explanatory, not a checkbox or filter. The other status buttons remain interactive filters.

In dark mode, the empty-day label uses the muted gray text color. Week view shows one clickable all-day blocked indicator per date, without repeating the month-view label underneath it. Its popover includes the saved reason as plain text. Blocked indicators remain visible when filtering booking statuses.

In the compact month layout, booking indicators are thin status-colored bars that fill the day width. Bars on blocked dates retain a dashed border and subdued fill, as on desktop. Event details remain available on click and in the overflow popover. Empty blocked days stack the icon above the label in the space below the date number; mobile cells retain their 76px minimum height. Resizing, filtering and asynchronous refreshes preserve these indicators; week view and overflow popovers keep the full event text.

Scheduling rules remain unchanged:

- Only administrators can access the calendar or change blocked dates. Mutations require POST and CSRF protection.
- Past dates cannot be blocked. Reasons retain the existing 255-character limit.
- Dates with active bookings require explicit confirmation. Blocking never deletes or modifies those bookings.
- Live change-quote holds prevent blocking, including after a conflict confirmation.
- Explicit event end times/dates, legacy end-time tags and the four-hour fallback retain their existing priority and overnight behavior.
- Ordinary form submissions still work through the original redirect/message path.

`admin_calendar` returns its current event/blocked-date data when requested with `X-Requested-With: XMLHttpRequest`. Both this response and mutation responses use `Cache-Control: no-store`. Event descriptions are rendered as plain text, and initial payloads use Django's escaped JSON script output.

Verification covers HTML/JSON parity, date validation, role/CSRF checks, conflicts, holds, duplicate blocks, unblocking and event end times. Optional browser checks in `app.test_admin_calendar_browser` exercise actual FullCalendar interactions, failure recovery, and desktop/390px/320px layouts in both themes. Enable those checks with `RUN_DESIGN_BROWSER=1` and install Playwright; the browser checks use Microsoft Edge on Windows.
