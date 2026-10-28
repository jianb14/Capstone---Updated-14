"""Only Admin and Customer are supported application roles.

The retired value appears only in negative fixtures to verify old accounts cannot
retain administrator privileges. Django is_staff and existing URLs are separate.
"""
from uuid import UUID

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.urls.converters import IntConverter, UUIDConverter

from . import urls
from .models import AuditLog, ChatMessage, ChatSession, User
from .views.chat import _admin_support_chat_sessions


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AccountRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = 'RolePassword!23'
        cls.admin = User.objects.create_user(username='roles-admin', email='roles-admin@example.com',
            password=cls.password, role='admin', email_verified=True)
        cls.customer = User.objects.create_user(username='roles-customer', email='roles-customer@example.com',
            password=cls.password, role='customer', email_verified=True)
        cls.legacy = User.objects.create_user(username='roles-retired', email='roles-retired@example.com',
            password=cls.password, role='staff', email_verified=True)
        cls.framework_flag = User.objects.create_user(username='roles-flagged', role='customer',
            is_staff=True, email_verified=True)

    def setUp(self):
        cache.clear()

    def test_only_supported_roles_are_valid_for_forms(self):
        field = User._meta.get_field('role')
        self.assertEqual(dict(field.choices), {'admin': 'Admin', 'customer': 'Customer'})
        for role in ('staff', 'unknown', ''):
            with self.subTest(role=role), self.assertRaises(ValidationError):
                field.clean(role, None)

    def test_login_preserves_admin_and_customer_destinations(self):
        for user, destination in ((self.admin, 'dashboard'), (self.customer, 'home')):
            with self.subTest(role=user.role):
                self.client.logout()
                response = self.client.post(reverse('login'), {'email': user.email, 'password': self.password})
                self.assertRedirects(response, reverse(destination), fetch_redirect_response=False)
                self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_retired_role_cannot_log_in_even_with_valid_password(self):
        response = self.client.post(reverse('login'), {'email': self.legacy.email, 'password': self.password})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid email or password.')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(AuditLog.objects.filter(user=self.legacy).exists())

    def test_admin_user_editor_is_retired_and_cannot_assign_any_role(self):
        self.client.force_login(self.admin)
        url = reverse('admin_user_edit', args=[self.customer.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        for role in ('admin', 'customer', 'staff', ''):
            response = self.client.post(url, {'first_name': 'Jamie', 'last_name': 'Rivera',
                'email': self.customer.email, 'phone_number': '09170000000', 'role': role})
            self.assertEqual(response.status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.role, 'customer')
        self.assertFalse(AuditLog.objects.exists())

    def test_unsupported_accounts_show_unknown_without_role_editor(self):
        self.client.force_login(self.admin)
        listing = self.client.get(reverse('admin_user_list'), {'search': self.legacy.username})
        self.assertContains(listing, 'Unknown role')
        self.assertNotIn('staff', listing.context['user_summary'])
        self.assertContains(self.client.get(reverse('admin_user_detail', args=[self.legacy.pk])), 'Unknown role')
        self.assertEqual(self.client.get(reverse('admin_user_edit', args=[self.legacy.pk])).status_code, 403)

    def test_public_signup_cannot_request_an_admin_or_retired_role(self):
        for index, role in enumerate(('admin', 'staff')):
            self.client.logout()
            email = f'role-signup-{index}@gmail.com'
            response = self.client.post(reverse('register'), {
                'first_name': 'Jamie', 'last_name': 'Rivera', 'username': f'role-signup-{index}',
                'email': email, 'phone': '09170000000', 'password': self.password,
                'confirm_password': self.password, 'role': role,
            }, REMOTE_ADDR=f'192.0.2.{index + 1}')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(User.objects.get(email=email).role, 'customer')

    def test_every_admin_route_denies_customer_and_retired_roles(self):
        protected = []
        for pattern in urls.urlpatterns:
            if not pattern.name:
                continue
            route = str(pattern.pattern)
            if not route.startswith(('staff/', 'api/staff/')) and pattern.name not in ('dashboard', 'ai_health'):
                continue
            kwargs = {}
            for key, converter in pattern.pattern.converters.items():
                if isinstance(converter, IntConverter):
                    kwargs[key] = 999999
                elif isinstance(converter, UUIDConverter):
                    kwargs[key] = UUID(int=1)
                else:
                    kwargs[key] = {'action': 'approve', 'kind': 'package', 'id': 'TRX-999999'}.get(key, 'sample')
            protected.append((pattern.name, reverse(pattern.name, kwargs=kwargs)))
        self.assertGreater(len(protected), 80)
        for user in (self.customer, self.legacy, self.framework_flag):
            self.client.force_login(user)
            for name, url in protected:
                for method in ('get', 'post'):
                    with self.subTest(role=user.role, is_staff=user.is_staff, route=name, method=method):
                        response = getattr(self.client, method)(url)
                        self.assertIn(response.status_code, (403, 404, 405))
        self.assertFalse(AuditLog.objects.exists())

    def test_chat_admin_identity_and_unread_counts_use_only_the_admin_role(self):
        for user in (self.customer, self.legacy, self.framework_flag):
            self.assertFalse(ChatMessage(sender=user, receiver=self.admin).is_from_admin)
        self.assertTrue(ChatMessage(sender=self.admin, receiver=self.customer).is_from_admin)
        session = ChatSession.objects.create(user=self.customer, title='Help with my event',
            is_admin_support=True, status='pending_admin')
        for user in (self.customer, self.legacy, self.framework_flag):
            ChatMessage.objects.create(session=session, sender=user, receiver=self.admin, message='Needs a reply')
        ChatMessage.objects.create(session=session, sender=self.admin, receiver=self.customer, message='Admin reply')
        self.assertEqual(_admin_support_chat_sessions().get(pk=session.pk).unread_admin_count, 3)
