# Admin audit history

`/staff/audit-log/` is a read-only, admin-only view. It shares the Concerns search, focus ring, dropdown, date-range, empty-state and pagination styles. The table shows eight activities by default, with Show 4/8 and a stable newest-first order using timestamp and record ID.

Search matches the full activity text, account name, username, email or `#LOG-<id>`. Role filters include Admin, Customer and System / removed account. Staff is not a supported account role; old Staff or invalid role query parameters fall back to all records. Any historical record linked to an unsupported role remains visible with an Unknown label. Optional date ranges require valid start and end dates, include both dates, and use Philippine time. Invalid ranges produce inline feedback. Results are private and are not cached.

Search, filters, pagination and browser Back/Forward update the table asynchronously. Failed requests retain the visible records and allow retry. Search cancellation and response sequencing prevent an older response from replacing newer results. The selected page size survives an empty result.

Clicking a row or its disclosure button opens inline details without a nested card: the full activity, audit ID, timestamp including seconds, and linked account information including account ID. Only one row is open at a time. Enter/Space operates the disclosure button; Escape closes it. Existing account records have a View account link. System records and records whose account was removed have a System label.

The audit model stores `user_id`, `action` and `created_at`. Linked account fields describe the current profile. Full activity text is escaped on the server. Expanded content stays within the table's visible width on small screens, including when the table is scrolled horizontally.

`admin_selects.js` supplies the shared dropdown behavior for Audit Logs and Concerns. It measures option labels so short menus fit without scrollbars, wraps long labels within the viewport, and only scrolls vertically when space is limited. It also handles keyboard selection, popover placement, outside clicks, scrolling, resizing and replacement of table footer controls.

Validation:

```powershell
.venv/Scripts/python.exe manage.py test app.test_admin_audit.AdminAuditTests app.test_admin_concerns.AdminConcernTests --settings=Project.test_settings --noinput
```

The opt-in `AdminAuditBrowserTests` suite uses Chrome/Playwright and isolated test accounts. Set `RUN_ADMIN_AUDIT_BROWSER=1` and run it against a disposable PostgreSQL test database. It covers asynchronous navigation, row disclosure, long activities, empty results, validation, failed requests/retries, keyboard controls, page-size preservation, and light/dark layouts at desktop, tablet and mobile widths.
