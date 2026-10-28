# Administrator onboarding

There are two account roles: admin and customer. Existing customer accounts cannot be promoted by an invitation. The user directory cannot edit, delete or reset account passwords, and the Django account admin cannot add accounts.

## Existing administrators

Every unverified administrator, including a Django-created superuser with a placeholder email, can set up their own accessible email in the **My Profile → Admin email verification** modal. The old `/staff/security/email/` URL redirects to My Profile and opens that modal. They must supply their current password and a code sent to the new inbox. The original email remains until verification succeeds. The code expires in five minutes, allows five incorrect guesses and is bound to the requesting session and current password. Code resends require a 60-second wait and recent password confirmation, valid for 15 minutes from the original confirmation. Resending does not extend that window. Request and guessing budgets also span sessions/resends.

After password login an unverified admin enters a restricted session on My Profile with the verification modal open. This permits only the read-only profile, own email verification and logout, until email verification succeeds. Existing admin sessions show a setup button on My Profile and a reminder in User Management pointing to that section. Sending, confirming and resending codes use asynchronous requests. Success closes the modal and updates the profile email and verification status in place. An unverified account cannot issue invitations. Customer signup and recovery routes cannot verify or recover an unverified administrator through an old placeholder email.

Refreshing an unfinished verification page, or closing and reopening its dialog, restores its current state in the same authenticated session. A valid code restores code entry. An expired code shows a single expired notice with a direct **Send new code** action, preserving the approved details. After the 15-minute password confirmation window, the details are restored and the current password is required again. Codes and passwords are never restored into the form. A different session cannot resume that challenge.

The six digit boxes accept numbers and support paste, autofill and keyboard navigation. Expiry and resend countdowns use the original server deadlines and keep their remaining time after refresh or reopening. **Resend code** and **Edit details** are separate actions. Once expired, code entry is hidden. A direct resend uses only the original server-held recipient and details, invalidates the previous code only after successful mail delivery, and independently enforces expiry, permission, session binding and resend limits. Changing details requires a new password confirmation.

Local and deployed databases are separate: each existing admin must verify their accessible inbox in each environment. Deploy the migration before starting the updated application:

```console
python manage.py migrate
```

## Creating an admin

An active, verified superuser sees **Create admin** in User Management. Ordinary admins do not. A trusted operator can explicitly designate another existing, verified admin using the deployment console:

```console
python manage.py admin_invite_permission real-admin@example.com
python manage.py admin_invite_permission real-admin@example.com --revoke
```

This grants only invitation permission, never superuser privileges. Only use the command for an identity you have independently authorized. Never mark an email verified without proof of inbox access.

1. The authorized creator enters the new admin's name, email, phone and their own current password.
2. A five-minute code is sent to the creator's verified inbox, naming the intended recipient.
3. Correct confirmation sends a single-use invitation to the recipient. It expires after 24 hours. No user exists yet.
4. The recipient opens the invitation and chooses their own validated password. The resulting account is verified, role `admin`, with no superuser, framework-admin or invitation permissions.

Recipient password setup opens in a dialog over the existing login screen. Required markers and field errors use the shared admin form styling, with a small gap below each input. Validation uses asynchronous requests and keeps errors next to their fields. Closing the dialog reveals the working login form without creating an account or consuming the invitation. Successful creation sends the recipient to login; invitation URLs stay token-free after the initial exchange.

The password checklist reuses the Register component and stylesheet: two columns with live indicators for 8+ characters, an uppercase letter, a number and a special character. The invitation form and backend enforce those same requirements. Backend checks for common passwords and similarity to account details also remain enabled.

Resending a recipient's invitation link requires another creator password confirmation and code; a successful resend replaces the old link. This is separate from resending an unfinished authorization code. Revoke requires the authorized admin's current password. Permission removal, deactivation or a creator password/email change invalidates outstanding invitations. Simultaneous acceptance is serialized and creates only one account. Mail failures leave accounts and prior valid invitations unchanged. Mail acceptance is not a guarantee of inbox delivery; check the configured provider if an accepted email does not arrive.

Duplicate pending invitations and mismatched resend targets are rejected before sending an authorization code. Confirmation and acceptance acquire the address and invitation locks in the same order, including when different creators act on the same recipient.

Passwords, invitation tokens and codes are never written to audit records. Only digests of codes/tokens are persisted. Invitation GET requests never create accounts, and forms use a token-free URL after storing the proof in a server-side session. The raw-token redirect sends no referrer; the token-free form permits same-origin referrers for CSRF and never sends them across origins. Security pages are not cached. Keep production HTTPS and secure cookies enabled. Email OTP is a practical verification layer; phishing-resistant login MFA is a separate future improvement.

The former public admin-creation endpoint and its hard-coded default credentials have been removed. Use the trusted Django `createsuperuser` console only for initial bootstrap, with a unique strong password, then verify that admin's own real inbox.
