# Application roles

The supported custom account roles are `admin` and `customer`, defined by
`User.ROLE_CHOICES`. Public registration always creates a customer; administrators
can assign either supported role through the user editor. Login rejects unsupported
role values before establishing an authenticated session.

Admin pages, booking/payment management, notifications, chat management, design
configuration and content editors no longer authorize the retired custom Staff
role. Existing authenticated sessions with an unsupported role cannot use these
admin endpoints. No accounts or transaction history are deleted or reassigned by
this cleanup. Any unsupported account data requires explicit administrative review;
it is never automatically promoted to Admin.

Unsupported accounts show an Unknown role badge in user management. Editing one
requires explicitly choosing Admin or Customer; the form does not default it to
Admin or mislabel it as Customer.

`/staff/` remains the existing admin URL prefix so links and bookmarks keep working.
Django's `is_staff` flag is retained for Django admin access and framework account
safeguards. It does not grant the custom Admin role. Existing superuser behavior is
preserved. Historical migrations remain unchanged; migration 0059 already removed
Staff from the field choices, so no schema migration is required for this cleanup.

Tests may deliberately construct unsupported role values to verify rejection of
old data. They do not represent a supported account type.

```powershell
.venv/Scripts/python.exe manage.py test app.test_account_roles --settings=Project.test_settings --noinput
```
