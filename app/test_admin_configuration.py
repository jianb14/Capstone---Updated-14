"""Atomic async settings saves and administrator profile security boundaries."""
import re
from datetime import timedelta

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, EmailOTPChallenge, ServiceChargeConfig, SiteSettings, User


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REQUEST_RATE_LIMITING_ENABLED=False)
class AdminConfigurationTests(TestCase):
    def setUp(self):
        from .test_site_settings_save import UnifiedSiteSettingsTests
        UnifiedSiteSettingsTests.setUp(self)

    def post(self, data):
        return self.client.post(reverse('admin_site_settings'), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_async_save_persists_every_section_and_returns_audit_metadata(self):
        response = self.post(self.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertIn('updated_at', response.json())
        self.settings.refresh_from_db(); self.config.refresh_from_db()
        self.assertEqual(self.settings.site_name, 'Updated business')
        self.assertEqual(self.settings.max_saved_designs, 35)
        self.assertEqual(self.config.amount, 1200)
        self.assertEqual(AuditLog.objects.filter(user=self.admin, action__startswith='Updated site settings,').count(), 1)
        self.assertEqual(list(response.wsgi_request._messages), [])

    def test_async_errors_preserve_all_saved_values(self):
        response = self.post({**self.data, 'contact_email':'not-email', 'admin_emails_for_notifications':'ok@example.com, broken',
                              'booking_min_duration_hours':'25', 'per_km_rate':'-1', 'max_saved_designs':'0'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue({'contact_email','admin_emails_for_notifications','booking_min_duration_hours','per_km_rate','max_saved_designs'} <= response.json()['errors'].keys())
        self.settings.refresh_from_db(); self.config.refresh_from_db()
        self.assertEqual(self.settings.site_name, 'Balloorina'); self.assertEqual(self.config.amount, 1000)
        self.assertFalse(AuditLog.objects.filter(user=self.admin).exists())

    def test_native_invalid_fields_keep_the_posted_values(self):
        response = self.client.post(reverse('admin_site_settings'), {**self.data, 'site_name':'', 'contact_phone':'09001112222'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '09001112222', status_code=400)
        self.assertContains(response, 'Updated shop', status_code=400)

    def test_optional_contacts_and_alert_recipient_normalization(self):
        response = self.post({**self.data, 'contact_email':'', 'contact_phone':'', 'facebook_link':'', 'instagram_link':'',
                              'admin_emails_for_notifications':'a@example.com, A@EXAMPLE.COM, a@example.com, b@example.com'})
        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.admin_emails_for_notifications, 'a@example.com, b@example.com')

    def test_settings_load_and_native_errors_without_a_shop_pin(self):
        self.config.shop_lat = self.config.shop_lng = None
        self.config.save(update_fields=['shop_lat','shop_lng'])
        response = self.client.get(reverse('admin_site_settings'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['site_form']['shop_lat'].value(),'')
        response = self.client.post(reverse('admin_site_settings'), {'settings_section':'design','max_saved_designs':'0'})
        self.assertEqual(response.status_code,400)
        self.assertContains(response,'max_saved_designs',status_code=400)

    def test_settings_require_admin_and_csrf_and_profile_is_not_a_user_editor(self):
        customer = User.objects.create_user(username='settings-customer', role='customer')
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse('admin_site_settings')).status_code, 403)
        self.assertEqual(self.post(self.data).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_profile')).status_code, 403)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.admin)
        self.assertEqual(secure.post(reverse('admin_site_settings'), self.data).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('admin_profile'), {'role':'customer','email':'bad@example.com'}).status_code, 405)

    def test_profile_shows_only_own_five_latest_actions_and_verification_prompt(self):
        other = User.objects.create_user(username='other-settings-admin', role='admin')
        for i in range(7): AuditLog.objects.create(user=self.admin, action=f'My action {i}')
        AuditLog.objects.create(user=other, action='Private other admin action')
        response = self.client.get(reverse('admin_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['recent_activity']), 5)
        self.assertNotContains(response, 'Private other admin action')
        self.assertContains(response, 'Set up and verify email')

    def test_admin_inline_password_flow_requires_code_preserves_session_and_rejects_replay(self):
        self.admin.email_verified = True; self.admin.email = 'settings-admin@example.com'
        self.admin.set_password('ExistingPassword!25'); self.admin.save()
        self.client.force_login(self.admin)
        def ajax(url, data): return self.client.post(reverse(url), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        response = ajax('change_password', {'old_password':'ExistingPassword!25','new_password1':'NewPassword!26','new_password2':'NewPassword!26'})
        self.assertTrue(response.json()['success'], response.content)
        code = re.search(r'(?m)^\d{6}$', mail.outbox[-1].body).group()
        self.admin.refresh_from_db(); self.assertTrue(self.admin.check_password('ExistingPassword!25'))
        profile = self.client.get(reverse('admin_profile'))
        self.assertTrue(profile.context['password_code_pending'])
        url = reverse('verify_change_password_otp')
        state = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        self.assertGreater(state['expiry_seconds'], 0); self.assertGreater(state['resend_wait'], 0)
        self.assertFalse(ajax('verify_change_password_otp', {'code':'abcdef'}).json()['success'])
        self.assertTrue(ajax('verify_change_password_otp', {'code':code}).json()['verified'])
        self.admin.refresh_from_db(); self.assertTrue(self.admin.check_password('NewPassword!26'))
        self.assertEqual(self.client.get(reverse('admin_profile')).status_code, 200)
        self.assertEqual(ajax('verify_change_password_otp', {'code':code}).status_code, 400)

    def test_expired_password_code_state_cannot_change_password(self):
        self.admin.email_verified = True; self.admin.email = 'settings-admin@example.com'
        self.admin.set_password('ExistingPassword!25'); self.admin.save(); self.client.force_login(self.admin)
        self.client.post(reverse('change_password'), {'old_password':'ExistingPassword!25','new_password1':'NewPassword!26','new_password2':'NewPassword!26'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        code = re.search(r'(?m)^\d{6}$', mail.outbox[-1].body).group()
        EmailOTPChallenge.objects.filter(user=self.admin).update(expires_at=timezone.now()-timedelta(seconds=1))
        response = self.client.post(reverse('verify_change_password_otp'), {'code':code}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['expiry_seconds'], 0)
        self.admin.refresh_from_db(); self.assertTrue(self.admin.check_password('ExistingPassword!25'))
