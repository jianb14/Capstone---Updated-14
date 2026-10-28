"""Read-only user administration, mail-backed access changes and bounded account data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, Lock
from unittest import skipUnless
from unittest.mock import patch

from django.core import mail
from django.db import close_old_connections, connection
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Booking, Payment, User
from .user_management import UserStatusError, change_user_access


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminUserTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='users-admin', email='admin@example.com', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='jamie', first_name='Jamie', last_name='Rivera',
            email='jamie@example.com', phone_number='09171234567', password='Customer!234', role='customer', email_verified=True)
        self.client.force_login(self.admin)
        self.url = reverse('admin_user_list')
        self.action = reverse('admin_user_toggle', args=[self.customer.pk])
        mail.outbox = []

    def post_access(self, action='deactivate', expected='1', **kwargs):
        return self.client.post(self.action, {'action': action, 'expected_active': expected}, **kwargs)

    def test_only_admin_can_access_directory_details_or_actions(self):
        paths = (self.url, reverse('admin_user_detail', args=[self.customer.pk]))
        self.client.logout()
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 302)
        self.client.force_login(self.customer)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.post_access().status_code, 403)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertEqual(mail.outbox, [])

    def test_retired_actions_are_blocked_for_get_and_post_without_changes(self):
        original = (self.customer.first_name, self.customer.email, self.customer.password, self.customer.role)
        for name in ('admin_user_edit', 'admin_user_delete', 'admin_user_reset_password'):
            for method in ('get', 'post'):
                response = getattr(self.client, method)(reverse(name, args=[self.customer.pk]), {
                    'first_name': 'Changed', 'email': 'hijack@example.com', 'role': 'admin'})
                self.assertEqual(response.status_code, 403, (name, method))
        self.customer.refresh_from_db()
        self.assertEqual((self.customer.first_name, self.customer.email, self.customer.password, self.customer.role), original)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(AuditLog.objects.exists())

    def test_directory_only_exposes_view_and_access_actions(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Profiles are read-only')
        self.assertContains(response, 'userDetailModal')
        self.assertContains(response, 'userAccessModal')
        self.assertContains(response, 'Clear user search')
        for name in ('admin_user_edit', 'admin_user_delete', 'admin_user_reset_password'):
            self.assertNotContains(response, reverse(name, args=[self.customer.pk]))
        self.assertNotContains(response, f'data-action-url="{reverse("admin_user_toggle", args=[self.admin.pk])}"')

    def test_framework_admin_cannot_bypass_edit_or_delete_policy(self):
        owner = User.objects.create_superuser(username='framework-owner', email='owner@example.com',
            password='Owner!234', role='admin', email_verified=True)
        self.client.force_login(owner)
        change_url = reverse('admin:app_user_change', args=[self.customer.pk])
        self.assertEqual(self.client.get(change_url).status_code, 200)
        self.assertEqual(self.client.post(change_url, {'username': 'changed'}).status_code, 403)
        delete_url = reverse('admin:app_user_delete', args=[self.customer.pk])
        self.assertEqual(self.client.post(delete_url, {'post': 'yes'}).status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.username, 'jamie')

    def test_search_input_is_bounded_and_rejects_database_control_characters(self):
        response = self.client.get(self.url, {'search': 'Jamie\x00'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['search_query'], 'Jamie')
        response = self.client.get(self.url, {'search': 'a' * 5000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['search_query']), 150)

    def test_list_defaults_to_eight_and_validates_page_sizes_and_page_numbers(self):
        User.objects.bulk_create([User(username=f'page-{index}', role='customer') for index in range(30)])
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['users']), 8)
        self.assertEqual(response.context['user_summary']['total'], 32)
        self.assertEqual(response.context['user_summary']['customers'], 31)
        self.assertEqual(len(self.client.get(self.url, {'per_page': '4'}).context['users']), 4)
        for value in ('100000', '0', '-1', 'bad'):
            self.assertEqual(len(self.client.get(self.url, {'per_page': value}).context['users']), 8)
        for page in ('invalid', '0', '-5', '99999'):
            self.assertEqual(self.client.get(self.url, {'page': page}).status_code, 200)
        response = self.client.get(self.url, {'page': 2, 'per_page': 8}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['page'], 2)
        self.assertEqual(response.json()['html'].count('data-user-row='), 8)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('<html', response.json()['html'])

    def test_search_name_phone_id_and_filters_with_global_summary(self):
        for query in ('Jamie Rivera', 'jamie@example.com', '09171234567', f'#USER-{self.customer.pk}'):
            with self.subTest(query=query):
                response = self.client.get(self.url, {'search': query})
                self.assertEqual(list(response.context['users']), [self.customer])
                self.assertEqual(response.context['user_summary']['total'], 2)
        self.assertEqual(list(self.client.get(self.url, {'role': 'admin'}).context['users']), [self.admin])
        self.assertEqual(len(self.client.get(self.url, {'role': 'unsupported', 'status': 'bad'}).context['users']), 2)
        response = self.client.get(self.url, {'status': 'inactive'})
        self.assertContains(response, 'No matching users')
        self.assertNotContains(response, '<thead>')
        self.assertNotContains(response, 'data-list-footer')

    def test_removed_users_stay_out_of_directory_and_cannot_be_reactivated(self):
        self.customer.deleted_at = timezone.now()
        self.customer.save(update_fields=['deleted_at'])
        self.assertNotContains(self.client.get(self.url), 'jamie@example.com')
        self.assertEqual(self.post_access('activate', '0').status_code, 404)
        for name in ('admin_user_edit', 'admin_user_delete', 'admin_user_reset_password'):
            self.assertEqual(self.client.post(reverse(name, args=[self.customer.pk])).status_code, 404)
        response = self.client.get(reverse('admin_user_detail', args=[self.customer.pk]))
        self.assertContains(response, 'Deleted account')
        self.assertNotContains(response, f'data-action-url="{self.action}"')

    def test_status_change_requires_post_valid_action_and_csrf(self):
        self.assertEqual(self.client.get(self.action).status_code, 405)
        for data in ({}, {'action': 'delete', 'expected_active': '1'}, {'action': 'deactivate', 'expected_active': 'yes'}):
            self.assertEqual(self.client.post(self.action, data).status_code, 400)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.admin)
        protected.get(self.url)
        self.assertEqual(protected.post(self.action, {'action': 'deactivate', 'expected_active': '1'}).status_code, 403)
        response = protected.post(self.action, {'action': 'deactivate', 'expected_active': '1'},
            HTTP_X_CSRFTOKEN=protected.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_deactivate_activate_email_and_repeat_requests_preserve_records(self):
        booking = Booking.objects.create(user=self.customer, event_date=date(2099, 1, 15), event_type='Birthday',
            event_location='Venue', total_price=5000, status='confirmed')
        Payment.objects.create(booking=booking, amount=2000, payment_method='gcash', payment_status='verified')
        response = self.post_access()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['changed'])
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertEqual(mail.outbox[0].to, [self.customer.email])
        self.assertIn('deactivated', mail.outbox[0].subject)
        self.assertIn('not been cancelled or deleted', mail.outbox[0].body)
        self.assertEqual(self.post_access().json()['changed'], False)
        self.assertEqual(len(mail.outbox), 1)
        response = self.post_access('activate', '0')
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertIn('activated', mail.outbox[1].subject)
        self.assertIn(reverse('login'), mail.outbox[1].body)
        self.assertEqual(self.post_access('activate', '0').json()['changed'], False)
        self.assertEqual(len(mail.outbox), 2)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(Payment.objects.filter(booking=booking).count(), 1)
        self.assertEqual(AuditLog.objects.filter(user=self.admin).count(), 2)

    def test_email_failure_rolls_back_status_and_audit_instead_of_false_success(self):
        for result in ('exception', 'zero'):
            with self.subTest(result=result), patch('app.user_management.EmailMultiAlternatives.send') as send:
                if result == 'exception':
                    send.side_effect = OSError('Email offline')
                else:
                    send.return_value = 0
                with self.assertLogs('app.user_management', level='ERROR'):
                    response = self.post_access()
                self.assertEqual(response.status_code, 503)
                self.assertIn('not changed', response.json()['message'])
                self.customer.refresh_from_db()
                self.assertTrue(self.customer.is_active)
                self.assertFalse(AuditLog.objects.exists())

    def test_missing_email_and_stale_confirmation_do_not_change_access(self):
        response = self.post_access(expected='0')
        self.assertEqual(response.status_code, 409)
        self.customer.email = ''
        self.customer.save(update_fields=['email'])
        self.assertEqual(self.post_access().status_code, 400)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertEqual(mail.outbox, [])

    def test_own_account_and_inactive_actor_protected(self):
        response = self.client.post(reverse('admin_user_toggle', args=[self.admin.pk]), {'action': 'deactivate', 'expected_active': '1'})
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        with self.assertRaises(UserStatusError):
            change_user_access(actor_id=self.admin.pk, target_id=self.customer.pk, active=False, expected_active=True, login_url='/login/')
        self.assertEqual(mail.outbox, [])

    def test_unverified_account_activation_does_not_verify_email_or_grant_admin_role(self):
        self.customer.is_active = self.customer.email_verified = False
        self.customer.save(update_fields=['is_active', 'email_verified'])
        self.assertEqual(self.post_access('activate', '0').status_code, 200)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.email_verified)
        self.assertEqual(self.customer.role, 'customer')
        self.assertIn('Complete email verification', mail.outbox[0].body)

    def test_deactivation_invalidates_existing_customer_session(self):
        customer_client = Client()
        customer_client.force_login(self.customer)
        self.assertEqual(customer_client.get(reverse('my_profile')).status_code, 200)
        self.assertEqual(self.post_access().status_code, 200)
        self.assertEqual(customer_client.get(reverse('my_profile')).status_code, 302)

    def test_details_use_credited_verified_payments_and_escape_profile_fields(self):
        self.customer.first_name = '<script>alert(1)</script>'
        self.customer.save(update_fields=['first_name'])
        for index in range(7):
            booking = Booking.objects.create(user=self.customer, event_date=date(2099, 1, 15), event_type='Birthday',
                event_location='Venue', total_price=5000, status='confirmed')
            Payment.objects.create(booking=booking, amount=100, payment_method='gcash', payment_status='verified', transaction_ref=f'PAID-{index}')
            Payment.objects.create(booking=booking, amount=500, payment_method='gcash', payment_status='pending', transaction_ref=f'PENDING-{index}')
            Payment.objects.create(booking=booking, amount=900, payment_method='gcash', payment_status='verified', applied_to_booking=False, transaction_ref=f'UNAPPLIED-{index}')
        url = reverse('admin_user_detail', args=[self.customer.pk])
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertIn('700.00', response.json()['html'])
        self.assertIn('&lt;script&gt;', response.json()['html'])
        self.assertNotIn('<script>alert(1)</script>', response.json()['html'])
        self.assertEqual(response.json()['html'].count('aria-label="View booking #'), 5)
        self.assertEqual(response.json()['html'].count('aria-label="View payment #'), 5)
        self.assertNotIn('admin_user_edit', response.json()['html'])
        self.assertIn('data-initial-user=', self.client.get(url).content.decode())


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminUserConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.first = User.objects.create_user(username='first-admin', email='first@example.com', role='admin', email_verified=True)
        self.second = User.objects.create_user(username='second-admin', email='second@example.com', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='locked-customer', email='locked@example.com', role='customer', email_verified=True)

    def run_together(self, pairs):
        barrier, sent, gate = Barrier(2), [], Lock()
        def send(email, **kwargs):
            with gate:
                sent.append(email.to)
            return 1
        def change(pair):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    user, changed = change_user_access(actor_id=pair[0], target_id=pair[1], active=False,
                        expected_active=True, login_url='http://testserver/login/')
                    return 200, changed
                except UserStatusError as error:
                    return error.status, False
            finally:
                close_old_connections()
        with patch('app.user_management.EmailMultiAlternatives.send', autospec=True, side_effect=send):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(change, pairs))
        return results, sent

    def test_simultaneous_duplicate_deactivation_sends_one_email(self):
        results, sent = self.run_together([(self.first.pk, self.customer.pk), (self.first.pk, self.customer.pk)])
        self.assertEqual(sorted(results), [(200, False), (200, True)])
        self.assertEqual(len(sent), 1)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)

    def test_cross_deactivation_cannot_disable_both_administrators(self):
        results, sent = self.run_together([(self.first.pk, self.second.pk), (self.second.pk, self.first.pk)])
        self.assertEqual(sorted(result[0] for result in results), [200, 403])
        self.assertEqual(User.objects.filter(role='admin', is_active=True).count(), 1)
        self.assertEqual(len(sent), 1)
