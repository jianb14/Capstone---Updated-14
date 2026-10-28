"""Privilege, mail, replay, bootstrap and concurrency regression coverage."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, local
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import admin_security as security, email_otp
from .models import AdminInvitation, AdminSecurityChallenge, AuditLog, EmailOTPChallenge, RequestRateBucket, User

PASSWORD = 'Creator!Secure234'
NEW_PASSWORD = 'Recipient!Secure786'


class AdminSecurityHelpers:
    def create_accounts(self):
        self.owner = User.objects.create_superuser(username='bootstrap-root', email='main@example.com', password=PASSWORD,
                                                   role='admin', email_verified=True)
        self.admin = User.objects.create_user(username='ordinary-admin', email='other@example.com', password=PASSWORD,
                                               role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='customer', email='customer@example.com', password=PASSWORD,
                                                  role='customer', email_verified=True)
        self.client.force_login(self.owner)
        mail.outbox = []

    def action(self, purpose='invite', action='send', data=None, client=None):
        return (client or self.client).post(reverse('admin_security_action', args=[purpose, action]), data or {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def invite_data(self, **extra):
        return dict(first_name='Jamie', last_name='Rivera', email='new-admin@example.com', phone_number='09171234567',
                    current_password=PASSWORD, **extra)

    def send_invite(self, data=None):
        response = self.action(data=data or self.invite_data())
        self.assertEqual(response.status_code, 200, response.content)
        return re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()

    def confirm_invite(self, code):
        return self.action(action='confirm', data={'code': code})

    def invitation(self):
        self.assertEqual(self.confirm_invite(self.send_invite()).status_code, 200)
        link = re.search(r'https?://[^\s]+', mail.outbox[-1].body).group()
        invitation = AdminInvitation.objects.latest('created_at')
        return invitation, link.replace('http://testserver', '')

    def age_challenges(self):
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=61))

    def recipient(self, link):
        client = Client()
        response = client.get(link)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['Location'], reverse('admin_invitation_accept'))
        return client


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REQUEST_RATE_LIMITING_ENABLED=False)
class AdminSecurityTests(AdminSecurityHelpers, TestCase):
    def setUp(self):
        self.create_accounts()

    def test_creation_requires_authorized_verified_creator_and_current_password(self):
        for user in (self.customer, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.action(data=self.invite_data()).status_code, 403)
            self.assertNotContains(self.client.get(reverse('admin_user_list')), 'data-open-invite', status_code=403 if user == self.customer else 200)
        self.client.force_login(self.owner)
        data = self.invite_data(); data['current_password'] = 'Incorrect!123'
        self.assertEqual(self.action(data=data).status_code, 400)
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        self.assertEqual(self.action(data=self.invite_data()).status_code, 403)
        self.assertEqual(mail.outbox, [])

    def test_permission_is_explicit_and_rechecked_without_permission_cache(self):
        permission = Permission.objects.get(content_type__app_label='app', codename='invite_administrator')
        self.assertFalse(security.can_invite(self.admin))
        self.admin.user_permissions.add(permission)
        self.assertTrue(security.can_invite(self.admin))
        self.admin.user_permissions.remove(permission)
        self.assertFalse(security.can_invite(self.admin))
        self.assertFalse(self.admin.is_superuser)

    def test_correct_mail_recipients_no_account_before_recipient_acceptance(self):
        code = self.send_invite()
        self.assertEqual(mail.outbox[0].to, [self.owner.email])
        self.assertIn('new-admin@example.com', mail.outbox[0].body)
        self.assertFalse(User.objects.filter(email='new-admin@example.com').exists())
        challenge = AdminSecurityChallenge.objects.get()
        self.assertNotEqual(challenge.code_digest, code)
        self.assertNotIn(PASSWORD, str(challenge.payload))
        response = self.confirm_invite(code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ['new-admin@example.com'])
        self.assertNotIn('admin-invitation/', response.content.decode())
        self.assertFalse(User.objects.filter(email='new-admin@example.com').exists())
        self.assertNotIn(code, ' '.join(AuditLog.objects.values_list('action', flat=True)))

    def test_invitee_sets_password_fixed_role_and_no_creator_privileges(self):
        invitation, link = self.invitation()
        recipient = self.recipient(link)
        self.assertFalse(User.objects.filter(email=invitation.email).exists())
        page = recipient.get(reverse('admin_invitation_accept'))
        self.assertContains(page, invitation.email)
        self.assertIn('no-store', page['Cache-Control'])
        response = recipient.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD, 'is_superuser': '1', 'role': 'customer', 'email': 'attacker@example.com'})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email=invitation.email)
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertEqual(user.role, 'admin')
        self.assertTrue(user.email_verified and user.is_active)
        self.assertFalse(user.is_superuser or user.is_staff or security.can_invite(user))
        invitation.refresh_from_db(); self.assertEqual(invitation.status, 'accepted'); self.assertEqual(invitation.token_digest, '')

    def test_link_is_single_use_and_get_does_not_consume(self):
        invitation, link = self.invitation()
        recipient = self.recipient(link)
        for _ in range(2):
            self.assertEqual(recipient.get(reverse('admin_invitation_accept')).status_code, 200)
        invitation.refresh_from_db(); self.assertEqual(invitation.status, 'pending')
        data = {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), data).status_code, 302)
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), data).status_code, 400)
        self.recipient(link).get(reverse('admin_invitation_accept'))
        self.assertEqual(User.objects.filter(email=invitation.email).count(), 1)

    def test_wrong_expired_or_cross_session_codes_cannot_issue_invite(self):
        code = self.send_invite()
        other = Client(); other.force_login(self.owner)
        self.assertEqual(self.action(action='confirm', data={'code': code}, client=other).status_code, 400)
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.assertEqual(self.confirm_invite(wrong).status_code, 400)
        challenge = AdminSecurityChallenge.objects.get()
        self.assertEqual(challenge.failed_attempts, 5)
        self.assertIsNotNone(challenge.consumed_at)
        self.assertEqual(self.confirm_invite(code).status_code, 400)
        self.assertFalse(AdminInvitation.objects.exists())

    def test_otp_expiry_and_password_change_invalidate_code(self):
        code = self.send_invite()
        AdminSecurityChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.confirm_invite(code).status_code, 400)
        self.age_challenges(); code = self.send_invite()
        self.owner.set_password(NEW_PASSWORD); self.owner.save(update_fields=['password'])
        # Preserve old binding in a service request to verify the password digest itself.
        request = RequestFactory().post('/'); request.user = self.owner; request.session = dict(self.client.session)
        with self.assertRaises(security.SecurityError):
            security.confirm_challenge(request, 'invite', code)
        self.assertFalse(AdminInvitation.objects.exists())

    def test_duplicate_confirmation_and_email_conflicts_do_not_promote(self):
        data = self.invite_data(); data['email'] = 'CUSTOMER@example.com'
        self.assertEqual(self.action(data=data).status_code, 400)
        code = self.send_invite()
        self.assertEqual(self.confirm_invite(code).status_code, 200)
        self.assertEqual(self.confirm_invite(code).status_code, 400)
        self.assertEqual(AdminInvitation.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.customer.refresh_from_db(); self.assertEqual(self.customer.role, 'customer')

    def test_account_created_after_invitation_blocks_acceptance(self):
        invitation, link = self.invitation()
        recipient = self.recipient(link)
        User.objects.create_user(username='late-customer', email=invitation.email.upper(), role='customer')
        response = recipient.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email=invitation.email, role='admin').exists())

    def test_expiry_revocation_and_creator_authorization_are_enforced(self):
        invitation, link = self.invitation()
        recipient = self.recipient(link)
        self.owner.is_active = False; self.owner.save(update_fields=['is_active'])
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code, 400)
        self.owner.is_active = True; self.owner.save(update_fields=['is_active'])
        invitation.expires_at = timezone.now() - timedelta(seconds=1); invitation.save(update_fields=['expires_at'])
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code, 400)
        self.assertFalse(User.objects.filter(email=invitation.email).exists())

    def test_revoke_requires_password_and_revoked_token_fails(self):
        invitation, link = self.invitation()
        recipient = self.recipient(link)
        url = reverse('admin_invitation_revoke', args=[invitation.pk])
        self.assertEqual(self.client.post(url, {'current_password': 'wrong'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'current_password': PASSWORD}).status_code, 200)
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code, 400)

    def test_resend_rotates_link_only_after_creator_password_and_new_code(self):
        invitation, old_link = self.invitation(); old_recipient = self.recipient(old_link)
        self.age_challenges()
        data = self.invite_data(resend_id=str(invitation.pk)); code = self.send_invite(data)
        self.assertEqual(self.confirm_invite(code).status_code, 200)
        new_link = re.search(r'https?://[^\s]+', mail.outbox[-1].body).group().replace('http://testserver', '')
        self.assertNotEqual(old_link, new_link)
        self.assertEqual(AdminInvitation.objects.count(), 1)
        self.assertEqual(old_recipient.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code, 400)
        self.assertContains(self.recipient(new_link).get(reverse('admin_invitation_accept')), invitation.email)

    def test_mail_failure_keeps_prior_code_and_invitation_unchanged(self):
        code = self.send_invite()
        with patch('app.admin_security.send_mail', side_effect=RuntimeError('provider down')):
            self.assertEqual(self.confirm_invite(code).status_code, 503)
        self.assertFalse(AdminInvitation.objects.exists())
        challenge = AdminSecurityChallenge.objects.get(); self.assertIsNone(challenge.consumed_at)
        self.assertEqual(self.confirm_invite(code).status_code, 200)
        invitation = AdminInvitation.objects.get(); old_digest = invitation.token_digest
        self.age_challenges(); code = self.send_invite(self.invite_data(resend_id=str(invitation.pk)))
        with patch('app.admin_security.send_mail', return_value=0):
            self.assertEqual(self.confirm_invite(code).status_code, 503)
        invitation.refresh_from_db(); self.assertEqual(invitation.token_digest, old_digest)

    def test_code_mail_failure_never_changes_admin_email(self):
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        with patch('app.admin_security.send_mail', return_value=0):
            self.assertEqual(self.action('email', data={'email': 'real@example.com', 'current_password': PASSWORD}).status_code, 503)
        self.assertFalse(AdminSecurityChallenge.objects.exists())
        self.owner.refresh_from_db(); self.assertFalse(self.owner.email_verified); self.assertEqual(self.owner.email, 'main@example.com')

    def test_every_unverified_admin_can_verify_own_email_only(self):
        for account in (self.owner, self.admin):
            account.email_verified = False; account.save(update_fields=['email_verified'])
            client = Client(); client.force_login(account)
            self.assertRedirects(client.get(reverse('admin_email_setup')),
                                 reverse('admin_profile') + '?verify_email=1#admin-email-verification')
            profile = client.get(reverse('admin_profile'))
            self.assertContains(profile, 'id="adminEmailModal"')
            self.assertContains(profile, 'data-open-email')
            self.assertIn('no-store', profile['Cache-Control'])
            target = f'verified-{account.pk}@example.com'
            response = self.action('email', data={'email': target, 'current_password': PASSWORD}, client=client)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mail.outbox[-1].to, [target])
            account.refresh_from_db(); self.assertNotEqual(account.email, target)
            code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
            response = self.action('email', 'confirm', {'code': code, 'user_id': self.customer.pk}, client)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['verified_email'], target)
            account.refresh_from_db(); self.assertTrue(account.email_verified); self.assertEqual(account.email, target)
            self.assertNotContains(client.get(reverse('admin_profile')), 'id="adminEmailModal"')
        self.customer.refresh_from_db(); self.assertEqual(self.customer.email, 'customer@example.com')

    def test_unverified_admin_login_is_restricted_to_own_email_setup(self):
        self.admin.email_verified = False; self.admin.save(update_fields=['email_verified'])
        self.client.logout()
        response = self.client.post(reverse('login'), {'email': self.admin.email, 'password': PASSWORD})
        destination = reverse('admin_profile') + '?verify_email=1#admin-email-verification'
        self.assertRedirects(response, destination)
        self.assertEqual(self.client.get(reverse('admin_user_list'))['Location'], destination)
        profile = self.client.get(reverse('admin_profile'))
        self.assertContains(profile, 'data-email-dialog data-auto-open')
        self.assertEqual(self.client.get(reverse('admin_user_list'), HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_notification_feed'), HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_profile')).status_code, 302)
        self.assertEqual(self.action(action='resend').status_code, 403)
        response = self.action('email', data={'email': 'real-admin@example.com', 'current_password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
        self.assertEqual(self.action('email', 'confirm', {'code': code}).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin_user_list')).status_code, 200)

    def test_unverified_admin_cannot_use_customer_email_verification_or_recovery(self):
        self.admin.email_verified = False; self.admin.save(update_fields=['email_verified'])
        self.assertFalse(email_otp.eligible(self.admin, EmailOTPChallenge.SIGNUP))
        self.assertFalse(email_otp.eligible(self.admin, EmailOTPChallenge.RESET))
        self.customer.email_verified = False
        self.assertTrue(email_otp.eligible(self.customer, EmailOTPChallenge.SIGNUP))

    def test_resend_cooldown_and_budgets_remain_enabled_when_global_limits_disabled(self):
        self.send_invite()
        self.assertEqual(self.action(data=self.invite_data()).status_code, 429)
        self.assertEqual(AdminSecurityChallenge.objects.count(), 1)
        for _ in range(6):
            self.action(data=self.invite_data())
        self.assertEqual(self.action(data=self.invite_data()).status_code, 429)
        self.assertTrue(RequestRateBucket.objects.exists())

    def test_invalid_payload_and_weak_password_never_create_admin(self):
        self.assertEqual(self.action(data={'email': 'bad', 'current_password': PASSWORD}).status_code, 400)
        invitation, link = self.invitation(); recipient = self.recipient(link)
        for password, confirm in (('short', 'short'), (NEW_PASSWORD, 'Different!234')):
            response = recipient.post(reverse('admin_invitation_accept'), {'password': password, 'confirm_password': confirm})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email=invitation.email).exists())

    def test_invitation_modal_ajax_validation_and_acceptance(self):
        invitation, link = self.invitation(); recipient = self.recipient(link)
        page = recipient.get(reverse('admin_invitation_accept'))
        self.assertContains(page, 'id="loginForm"')
        self.assertContains(page, 'id="adminAcceptModal"')
        self.assertContains(page, 'action="' + reverse('login') + '" id="loginForm"')
        for data, expected in (({}, {'password', 'confirm_password'}),
                               ({'password': NEW_PASSWORD, 'confirm_password': 'Different!234'}, {'confirm_password'})):
            response = recipient.post(reverse('admin_invitation_accept'), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(set(response.json()['errors']), expected)
            self.assertFalse(User.objects.filter(email=invitation.email).exists())
            self.assertIn('no-store', response['Cache-Control'])
        response = recipient.post(reverse('admin_invitation_accept'),
            {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True, 'redirect_url': reverse('login')})
        self.assertTrue(User.objects.get(email=invitation.email).email_verified)
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'),
            {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 400)

    def test_invitation_password_requirements_match_registration(self):
        invitation, link = self.invitation(); recipient = self.recipient(link)
        page = recipient.get(reverse('admin_invitation_accept'))
        self.assertContains(page, '8+ characters')
        self.assertContains(page, 'id="invite-rule-uppercase"')
        for password in ('QZ!49N8', 'qz!49n8x', 'QZ!ABNXX', 'QZ149N8X'):
            response = recipient.post(reverse('admin_invitation_accept'),
                {'password': password, 'confirm_password': password}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 400)
            self.assertFalse(User.objects.filter(email=invitation.email).exists())
        response = recipient.post(reverse('admin_invitation_accept'),
            {'password': 'QZ!49N8X', 'confirm_password': 'QZ!49N8X'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.get(email=invitation.email).check_password('QZ!49N8X'))

    def test_csrf_http_methods_no_public_creation_and_native_add_are_blocked(self):
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.owner)
        for action in ('send', 'resend', 'confirm'):
            self.assertEqual(secure.post(reverse('admin_security_action', args=['invite', action]), self.invite_data()).status_code, 403)
            self.assertEqual(self.client.get(reverse('admin_security_action', args=['invite', action])).status_code, 405)
        self.assertEqual(self.client.get('/make-me-admin-secret-123/').status_code, 404)
        self.assertEqual(self.client.get(reverse('admin:app_user_add')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_invitation_list')).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin_invitation_list')).status_code, 403)

    def test_trusted_console_grant_and_revoke_do_not_change_roles_or_elevate_customer(self):
        from io import StringIO
        call_command('admin_invite_permission', self.admin.email, stdout=StringIO())
        self.assertTrue(security.can_invite(self.admin))
        call_command('admin_invite_permission', self.admin.email, revoke=True, stdout=StringIO())
        self.assertFalse(security.can_invite(self.admin))
        with self.assertRaises(CommandError):
            call_command('admin_invite_permission', self.customer.email, stdout=StringIO())
        self.admin.refresh_from_db(); self.assertFalse(self.admin.is_superuser or self.admin.is_staff)

    def test_pending_invitation_dies_when_creator_password_email_or_permission_changes(self):
        permission = Permission.objects.get(content_type__app_label='app', codename='invite_administrator')
        self.admin.user_permissions.add(permission)
        self.client.force_login(self.admin)
        invitation, link = self.invitation(); recipient = self.recipient(link)
        self.admin.user_permissions.remove(permission)
        data = {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), data).status_code, 400)
        self.admin.user_permissions.add(permission)
        self.admin.email = 'changed@example.com'; self.admin.save(update_fields=['email'])
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), data).status_code, 400)
        self.admin.email = invitation.creator_email; self.admin.set_password(NEW_PASSWORD)
        self.admin.save(update_fields=['email', 'password'])
        self.assertEqual(recipient.post(reverse('admin_invitation_accept'), data).status_code, 400)

    def test_acceptance_requires_csrf_and_referrer_policy_supports_secure_same_origin_post(self):
        _, link = self.invitation()
        strict = Client(enforce_csrf_checks=True)
        strict.get(link, secure=True)
        page = strict.get(reverse('admin_invitation_accept'), secure=True)
        self.assertEqual(page['Referrer-Policy'], 'same-origin')
        data = {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}
        self.assertEqual(strict.post(reverse('admin_invitation_accept'), data, secure=True).status_code, 403)
        data['csrfmiddlewaretoken'] = strict.cookies['csrftoken'].value
        self.assertEqual(strict.post(reverse('admin_invitation_accept'), data, secure=True,
            HTTP_ORIGIN='https://testserver', HTTP_REFERER='https://testserver' + reverse('admin_invitation_accept')).status_code, 302)

    def test_email_setup_rejects_existing_address_and_invitation_recipient_conflict(self):
        invitation, _ = self.invitation()
        self.admin.email_verified = False; self.admin.save(update_fields=['email_verified'])
        self.client.force_login(self.admin)
        for address in (self.customer.email, invitation.email):
            self.assertEqual(self.action('email', data={'email': address, 'current_password': PASSWORD}).status_code, 400)
        self.admin.refresh_from_db(); self.assertFalse(self.admin.email_verified)

    def test_link_tampering_authenticated_acceptance_and_incomplete_code_are_rejected(self):
        invitation, link = self.invitation()
        prefix, token = link.rstrip('/').rsplit('/', 1)
        bad_link = prefix + '/' + ('A' if token[0] != 'A' else 'B') + token[1:] + '/'
        self.assertNotContains(self.recipient(bad_link).get(reverse('admin_invitation_accept')), 'Welcome to the team')
        self.client.get(link)
        self.assertEqual(self.client.post(reverse('admin_invitation_accept'), {'password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}).status_code, 400)
        self.assertFalse(User.objects.filter(email=invitation.email).exists())

    def test_pending_code_is_restored_after_page_refresh_in_the_same_session(self):
        self.send_invite()
        response = self.client.get(reverse('admin_user_list'))
        self.assertTrue(response.context['pending_invite_security'])
        self.assertContains(response, 'data-pending-code="1"')

        other = Client(); other.force_login(self.owner)
        self.assertFalse(other.get(reverse('admin_user_list')).context['pending_invite_security'])
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        self.action('email', data={'email': 'real-inbox@example.com', 'current_password': PASSWORD})
        response = self.client.get(reverse('admin_profile'))
        self.assertTrue(response.context['pending_security'])
        self.assertContains(response, 'data-pending-code="1"')

    def test_send_and_refresh_use_the_original_server_deadlines(self):
        response = self.action(data=self.invite_data())
        self.assertEqual(response.status_code, 200)
        challenge = AdminSecurityChallenge.objects.get()
        timing = response.json()
        self.assertEqual(timing['expires_at'], challenge.expires_at.isoformat())
        self.assertEqual(timing['resend_available_at'], (challenge.created_at + timedelta(seconds=60)).isoformat())
        self.assertTrue(0 < timing['expires_in'] <= 300)
        self.assertTrue(0 < timing['resend_after'] <= 60)
        AdminSecurityChallenge.objects.filter(pk=challenge.pk).update(
            created_at=timezone.now() - timedelta(seconds=45), expires_at=timezone.now() + timedelta(seconds=180))
        challenge.refresh_from_db()
        response = self.client.get(reverse('admin_user_list'))
        state = response.context['pending_invite_security']
        self.assertEqual(state['expires_at'], challenge.expires_at.isoformat())
        self.assertTrue(0 < state['expires_in'] <= 180)
        self.assertTrue(0 < state['resend_after'] <= 15)
        self.assertContains(response, 'data-code-expires-at="' + challenge.expires_at.isoformat() + '"')
        self.assertEqual(len(mail.outbox), 1)

    def test_expired_code_restores_expired_display_without_bypassing_server_checks(self):
        code = self.send_invite()
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=301),
                                              expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.get(reverse('admin_user_list'))
        state = response.context['pending_invite_security']
        self.assertTrue(state)
        self.assertEqual(state['stage'], 'expired')
        self.assertContains(response, 'data-pending-code="0"')
        self.assertEqual((state['expires_in'], state['resend_after']), (0, 0))
        self.assertEqual(self.confirm_invite(code).status_code, 400)
        self.assertFalse(AdminInvitation.objects.exists())
        self.assertEqual(self.action(data=self.invite_data()).status_code, 200)

    def test_direct_resend_keeps_approved_details_and_rejects_old_code(self):
        with patch('app.admin_security.secrets.randbelow', return_value=42):
            old_code = self.send_invite()
        previous = AdminSecurityChallenge.objects.get()
        self.age_challenges()
        with patch('app.admin_security.secrets.randbelow', return_value=43):
            response = self.action(action='resend', data={'email': 'attacker@example.com', 'first_name': 'Changed', 'role': 'admin'})
        self.assertEqual(response.status_code, 200, response.content)
        current = AdminSecurityChallenge.objects.latest('created_at')
        self.assertEqual(current.target_email, previous.target_email)
        self.assertEqual(current.payload, previous.payload)
        self.assertEqual(mail.outbox[-1].to, [self.owner.email])
        self.assertEqual(self.confirm_invite(old_code).status_code, 400)
        self.assertEqual(self.confirm_invite('000043').status_code, 200)
        self.assertEqual(AdminInvitation.objects.get().email, previous.target_email)

    def test_direct_resend_enforces_cooldown_session_and_original_reauth_window(self):
        self.send_invite()
        self.assertEqual(self.action(action='resend').status_code, 429)
        other = Client(); other.force_login(self.owner)
        self.assertEqual(self.action(action='resend', client=other).status_code, 409)
        previous = AdminSecurityChallenge.objects.get()
        payload = {**previous.payload, '_reauth_at': (timezone.now() - timedelta(minutes=16)).isoformat()}
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=61),
                                              expires_at=timezone.now() - timedelta(seconds=1), payload=payload)
        response = self.action(action='resend')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'reauth_required')
        state = self.client.get(reverse('admin_user_list')).context['pending_invite_security']
        self.assertEqual(state['stage'], 'details')
        self.assertEqual(state['email'], previous.target_email)
        self.assertEqual(len(mail.outbox), 1)

    def test_direct_resend_failure_preserves_code_and_password_change_invalidates_resend(self):
        code = self.send_invite(); previous_id = self.client.session['admin_security_invite']
        self.age_challenges()
        with patch('app.admin_security.send_mail', return_value=0):
            self.assertEqual(self.action(action='resend').status_code, 503)
        self.assertEqual(self.client.session['admin_security_invite'], previous_id)
        self.assertEqual(AdminSecurityChallenge.objects.count(), 1)
        request = RequestFactory().post('/'); request.user = self.owner; request.session = dict(self.client.session)
        self.owner.set_password(NEW_PASSWORD); self.owner.save(update_fields=['password'])
        with self.assertRaises(security.SecurityError) as raised:
            security.resend_challenge(request, 'invite')
        self.assertEqual(raised.exception.code, 'reauth_required')
        self.assertEqual(len(mail.outbox), 1)

    def test_email_setup_can_resend_only_to_the_original_inbox(self):
        self.owner.email_verified = False; self.owner.save(update_fields=['email_verified'])
        self.assertEqual(self.action('email', data={'email': 'real@example.com', 'current_password': PASSWORD}).status_code, 200)
        self.age_challenges()
        response = self.action('email', 'resend', {'email': 'attacker@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ['real@example.com'])
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
        self.assertEqual(self.action('email', 'confirm', {'code': code}).status_code, 200)
        self.owner.refresh_from_db(); self.assertEqual(self.owner.email, 'real@example.com')

    def test_resends_do_not_extend_the_password_confirmation_window(self):
        self.send_invite()
        previous = AdminSecurityChallenge.objects.get()
        proof_time = (timezone.now() - timedelta(minutes=14)).isoformat()
        AdminSecurityChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=61),
            payload={**previous.payload, '_reauth_at': proof_time})
        self.assertEqual(self.action(action='resend').status_code, 200)
        current = AdminSecurityChallenge.objects.latest('created_at')
        self.assertEqual(current.payload['_reauth_at'], proof_time)

    def test_direct_resend_rechecks_permission_and_current_email(self):
        permission = Permission.objects.get(content_type__app_label='app', codename='invite_administrator')
        self.admin.user_permissions.add(permission)
        self.client.force_login(self.admin)
        self.send_invite()
        self.age_challenges()
        self.admin.user_permissions.remove(permission)
        self.assertEqual(self.action(action='resend').status_code, 403)
        self.admin.user_permissions.add(permission)
        self.admin.email = 'changed@example.com'
        self.admin.save(update_fields=['email'])
        response = self.action(action='resend')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'reauth_required')
        self.assertEqual(len(mail.outbox), 1)

    def test_conflicting_invites_and_wrong_resend_details_fail_before_sending_a_code(self):
        invitation, _ = self.invitation()
        self.age_challenges()
        previous_count = len(mail.outbox)
        self.assertEqual(self.action(data=self.invite_data()).status_code, 409)
        wrong = self.invite_data(resend_id=str(invitation.pk)); wrong['email'] = 'different@example.com'
        self.assertEqual(self.action(data=wrong).status_code, 409)
        self.assertEqual(len(mail.outbox), previous_count)

    @override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.PBKDF2PasswordHasher', 'django.contrib.auth.hashers.MD5PasswordHasher'])
    def test_password_hash_upgrade_preserves_the_session_and_otp_binding(self):
        code = self.send_invite()
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.password.startswith('pbkdf2_sha256$'))
        response = self.confirm_invite(code)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AdminInvitation.objects.count(), 1)
        from django.contrib.auth.hashers import make_password
        invitation = AdminInvitation.objects.get()
        self.owner.password = make_password(PASSWORD, hasher='md5')
        self.owner.save(update_fields=['password'])
        self.client.force_login(self.owner)
        response = self.client.post(reverse('admin_invitation_revoke', args=[invitation.pk]), {'current_password': PASSWORD})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.get(reverse('admin_user_list')).status_code, 200)


@skipUnless(connection.vendor == 'postgresql', 'Real row-lock concurrency requires PostgreSQL')
@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REQUEST_RATE_LIMITING_ENABLED=False)
class AdminSecurityConcurrencyTests(AdminSecurityHelpers, TransactionTestCase):
    def setUp(self):
        self.create_accounts()

    def test_concurrent_acceptance_creates_exactly_one_admin(self):
        invitation, _ = self.invitation()
        proof = {'id': str(invitation.pk), 'digest': invitation.token_digest}
        barrier = Barrier(2)
        def accept():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return security.accept_invitation(proof, NEW_PASSWORD).pk
                except security.SecurityError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: accept(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(User.objects.filter(email=invitation.email).count(), 1)

    def test_concurrent_code_confirmation_sends_one_invitation(self):
        code = self.send_invite(); session = dict(self.client.session); barrier = Barrier(2)
        def confirm():
            close_old_connections()
            try:
                request = RequestFactory().post('/'); request.user = User.objects.get(pk=self.owner.pk); request.session = dict(session)
                barrier.wait(timeout=10)
                try:
                    return str(security.confirm_challenge(request, 'invite', code).pk)
                except security.SecurityError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(AdminInvitation.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_second_creator_confirmation_cannot_deadlock_invitation_acceptance(self):
        owner_code = self.send_invite()
        self.admin.user_permissions.add(Permission.objects.get(content_type__app_label='app', codename='invite_administrator'))
        request = RequestFactory().post('/'); request.user = self.admin; request.session = {}
        security.issue_challenge(request, 'invite', PASSWORD, 'new-admin@example.com', {
            'first_name': 'Jamie', 'last_name': 'Rivera', 'phone_number': '09171234567'})
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group()
        self.assertEqual(self.confirm_invite(owner_code).status_code, 200)
        invitation = AdminInvitation.objects.get()
        proof = {'id': str(invitation.pk), 'digest': invitation.token_digest}
        thread_state, email_locked, accept_ready = local(), Event(), Event()
        original_lock = security.lock_email_address
        def ordered_lock(email):
            if thread_state.kind == 'confirm':
                result = original_lock(email)
                email_locked.set()
                if not accept_ready.wait(10):
                    raise TimeoutError('Recipient did not reach the address lock')
                return result
            accept_ready.set()
            if not email_locked.wait(10):
                raise TimeoutError('Creator did not acquire the address lock')
            return original_lock(email)
        def run(kind):
            close_old_connections(); thread_state.kind = kind
            try:
                if kind == 'accept':
                    return security.accept_invitation(proof, NEW_PASSWORD).pk
                try:
                    return security.confirm_challenge(request, 'invite', code)
                except security.SecurityError:
                    return None
            finally:
                close_old_connections()
        with patch('app.admin_security.lock_email_address', side_effect=ordered_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                confirmation, acceptance = pool.submit(run, 'confirm'), pool.submit(run, 'accept')
                self.assertIsNone(confirmation.result(timeout=20))
                self.assertIsInstance(acceptance.result(timeout=20), int)
        self.assertEqual(User.objects.filter(email=invitation.email).count(), 1)
