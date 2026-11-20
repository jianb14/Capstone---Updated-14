# Booking delete dialog and admin login feedback

Latest requested behavior: My Bookings deletion should match Request Changes,
with a solid red Delete button and white text;
admin login should use the existing custom feedback used by customers.

## Changes

- Kept the existing owner-checked POST deletion and account modal lifecycle.
  Updated its header, subtitle, description, close control, Cancel/Delete footer
  and scoped styles to match Request Changes (600px width, 24px radius, neutral
  surfaces, responsive spacing and light/dark colors). The destructive action uses
  the admin Users Deactivate button's #ba3c45 with white text and #a8343d on hover.
- Focus starts on Cancel; Escape/Cancel return focus and send no delete request.
  Phone layout is centered and above the floating support launcher.
- The admin shell loads existing local feedback assets and sends Django messages
  to `AppToast`. The previous unconditional `Swal.mixin` caused admin login feedback
  to keep using SweetAlert. Legacy SweetAlert action confirmations are preserved.
- Scoped server-message iteration variables so multiple messages can execute safely.

## Verification

New real-browser tests in `app/test_booking_delete_login_browser.py` exercise actual
login and deletion routes on an isolated test server. They compare rendered booking
dialog dimensions, radius, padding, heading size, surface and text colors to the actual Request Changes dialog at
1440px/390px in both themes; verify keyboard focus and cancellation without a POST;
and verify confirmed deletion submits once and shows existing custom feedback.

Initial browser runs reproduced missing custom admin login feedback and the old
450px/8px dialog. Expanded comparisons caught old light paragraph styles and a dark
body-color difference. Screenshots caught the inherited mobile bottom-sheet layout.

Final browser run: **3 passed** (37.430 seconds). All four desktop/mobile theme
comparisons pass, as do actual admin login and one-POST deletion checks.
The earlier implementation review had no remaining findings. Django system check and
`git diff --check` pass.

Related regression run: **35 passed**:

```powershell
.venv/Scripts/python.exe manage.py test app.test_toast_ui app.test_customer_booking_modals app.test_admin_catalog app.test_admin_configuration --settings=Project.test_settings --noinput
```

Browser command:

```powershell
$env:RUN_DESIGN_BROWSER='1'
.venv/Scripts/python.exe manage.py test app.test_booking_delete_login_browser --settings=Project.test_settings --noinput
```

Latest browser log: `.booking-followup-check/booking-delete-request-style-final.log`.
Earlier logs: `.booking-followup-check/booking-delete-login-final.log` and
`.booking-followup-check/booking-delete-login-regression.log`.
Screenshots: `.booking-followup-check/booking-delete-login/`.
No real account or booking was deleted; all mutations use isolated SQLite fixtures.
The earlier task's full-suite failures remain recorded in
`docs/booking-status-email-verification.md`; the full suite was not repeated for
this scoped UI change.
