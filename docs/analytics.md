# Admin reports and analytics

`/staff/analytics/` is restricted to the admin role. Filters update the report with a GET request returning a rendered fragment; navigation history and the PDF export retain the applied period. An aborted, failed or older request cannot replace a more recent result. The previous report stays visible on errors.

## Date and comparison rules

- **Event date** selects bookings scheduled within the inclusive date range (the default).
- **Booking submission date** selects bookings submitted within Philippine calendar dates, using a half-open midnight-to-midnight timestamp range.
- Today, 7 days and 30 days end on today's Philippine date. Their comparison is the immediately preceding interval of the same length.
- This month is month-to-date, compared with the previous calendar month through the matching day, capped at that month's last day. Extra days have no comparison point.
- Custom dates compare against the immediately preceding interval of the same length. Incomplete, invalid or reversed ranges return validation errors.
- All time covers actual matching booking dates (including future scheduled events) and recorded receipt dates, with no invented previous-period comparison.
- Percentage growth is undefined when the previous total is zero; the UI explains that baseline instead of claiming 100% growth.

All views use the same event filter. Booking KPIs and charts use the same cohort and grouped booking/payment read. Receipt-date collections use the reporting date range independently of booking dates. Large date ranges use bounded daily, weekly, monthly or yearly buckets. Reading this page does not expire or change booking records.

## Metrics

- **Bookings:** all booking statuses in the cohort.
- **Completed booking value:** final `total_price` for completed bookings only. This is not proof of cash received. The average divides this amount by the completed booking count.
- **Verified collections:** payment amounts with `payment_status='verified'` and `applied_to_booking=True`, belonging to the selected bookings, regardless of payment date. Pending, rejected and unapplied change payments are excluded. This is not net of refunds and is not an accounting profit report.
- **Completion / cancellation rates:** completed / cancelled bookings divided by all selected bookings. Cancel-requested bookings remain a separate status.
- **Customers with bookings:** distinct customer IDs in the selected cohort, rather than all registered accounts.

The Overview charts show the trend (one metric/unit at a time), current booking statuses, event mix and main setup demand. Each booking contributes one main setup; optional add-ons are excluded from that overview. Event and offer charts show six leading selections plus a grouped remainder. Accessible data summaries accompany the charts.

## Business analytics tabs

- **Bookings & Demand:** expiry/cancellation outcomes; committed events by actual event month, weekday and start hour; separate package, entrance arch and welcome stand selections. Committed demand includes confirmed, cancel-requested and completed bookings. Missing start times are flagged. Offer selections cover all cohort statuses and count each distinct selection once per booking. Historical names are matched to the catalog, then recognizable historical prefixes; unknown selections are flagged. Whole completed booking values containing each offer are available separately, explicitly overlapping and not attributed item revenue.
- **Payments:** recorded collections within the reporting period, independently of when the bookings were submitted or scheduled; payment methods; and payment progress/balances of the selected booking cohort. Collections use `received_at` (manual proof submission/provider receipt), then `paid_at` (verification) only as an explicit fallback. Verified payments missing both are flagged across all dates under the same event filter and excluded from dated totals. No checkout creation date is substituted.
- **Balances:** pending-payment, confirmed, cancel-requested and completed bookings only. Pending quotations, cancelled and expired bookings are excluded. Status is derived from verified applied payments, not `Booking.payment_status`. Remaining balances are clamped per booking; excess on one booking never offsets another. Zero-value bookings have no remaining balance.
- **Customers:** distinct customers with completed events in the cohort through today. A returning customer had a completed event on an earlier event date before their first completed event in the selected cohort (across all event types). Each customer is classified once. Future reservations or later bookings cannot retroactively establish earlier repeat history.
- **Reviews:** valid 1–5 ratings on eligible completed events, average with review count, and distinct reviewed-event coverage. Missing reviews do not become zero ratings. No eligible denominator displays an unavailable value rather than a false 0%.

Tabs and filters update asynchronously and retain history. PDF includes the business summaries. Excel includes separate booking-cohort collections and receipt-period collections sheets, business insights and offer demand, with definitions explaining the differing scopes.

Both export buttons download all analytics views under the **applied** filter, even when a different tab is active or date edits have not been submitted. Export links freeze the resolved dates and comparison mode; month-to-date retains its matching previous-month comparison, and all-time retains no comparison. PDF includes the trend appendix, methods, offer selections and rating distribution. Excel includes numeric chart series, period comparisons, source detail sheets, frozen headers, filters and print settings. User text is written as literal text rather than spreadsheet formulas.

Charts retain their instances during same-view filter changes and animate between values. The graph layout packs each column independently, expands a final unpaired card across the available width and recalculates when details open or the viewport changes. Horizontal charts size their height to their category count. Motion respects the device's reduced-motion preference, and emphasized report definitions use explicit theme-aware text colors.

Statuses and payments reflect the latest recorded state; this is not historical status reconstruction. The PDF uses the same calculation service and frozen resolved dates. Excel selects the same bookings and includes only their verified, applied payments in the collections sheet; the definitions sheet records the filter basis.

## Interface and verification

The page reuses Admin Concerns controls, focus rings and light/dark colors. Motion respects `prefers-reduced-motion`. Chart.js 4.5.1 is vendored in `static/vendor/chartjs/` with its MIT license, so charts do not depend on a runtime CDN request.

Backend regression coverage: `app.test_admin_analytics`, `app.test_analytics_insights` and `app.test_analytics_pdf`. Optional Playwright coverage: set `RUN_ADMIN_ANALYTICS_BROWSER=1` and run `app.test_admin_analytics_browser`; it uses local Chrome and a disposable test database, with desktop/mobile themes, all business tabs, async filters/history, late responses, validation, empty states and request failures.
