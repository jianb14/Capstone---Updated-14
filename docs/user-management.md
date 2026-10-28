# Administrator user management

User profiles are read-only in the admin directory. Admins can view account details
and explicitly activate or deactivate another account. General profile editing,
role changes, account deletion and admin-initiated password reset are unavailable.
The retired URLs reject requests. The built-in Django admin also disallows
editing or deleting existing user accounts. Customer self-service profile, recovery and
verified account-deletion flows remain separate.

The directory excludes permanently removed accounts. Its four KPIs cover all
remaining accounts, independently of search and filters. Search supports names,
email, username, phone and user ID. The default page size is 8; Show also offers 4.
Filters, pagination, details and access updates use JSON requests without reloading
the document. Direct account URLs open the same directory with a details modal.
Archived transaction owners can be viewed but cannot be reactivated.

Access updates require an authenticated active admin, POST and CSRF protection.
The request specifies its intended action and the status shown in the confirmation;
it never blindly toggles the current value. Duplicate requests for an already
applied state do not send another email. The actor and target account are locked
in a stable order so simultaneous requests cannot bypass access checks. An admin
cannot change their own access or deactivate the last active administrator.

Each successful change sends a plain-text and HTML notification through the
configured Django email backend (Brevo in production). Account notifications are
independent of the optional booking/concern admin-alert setting. Missing or invalid
recipient addresses prevent access changes. Provider errors or zero accepted
messages roll back both the account update and its audit entry. Provider acceptance
does not prove delivery to a recipient's inbox; delivery can be checked in Brevo.

Deactivation blocks subsequent authenticated customer requests. It does not cancel
bookings, delete payment records, change roles or mark an email address verified.
Activation restores access but still requires normal email verification at login.
No database migration is required for this redesign.

Successful access changes, authorization-code sends/resends, invitation sends/resends
and revocations show the shared top-right notification. It remains visible above
the modal, then fades away after three seconds (paused while hovered or focused).
Operational failures use an error notification; field validation stays below its
input. Opening details, searching and paging do not produce success notifications.
Disabled or busy invitation buttons have no hover effect and cannot submit twice.
