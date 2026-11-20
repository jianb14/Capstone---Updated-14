"""PostgreSQL integration checks for delivery/chat lock ordering."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time

from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse

from .models import Booking, ChatMessage, ChatSession, Payment, User
from .test_design_delivery import TempMediaMixin, _design_upload


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DesignDeliveryChatConcurrencyTests(TempMediaMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username='concurrent-admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='concurrent-customer', role='customer',
            email='customer@example.com', email_verified=True)
        self.booking = Booking.objects.create(user=self.customer, status='confirmed', event_date=date(2099, 6, 15),
            event_time=time(10), event_location='Venue', package_type='Package A', total_price=5000)
        Payment.objects.create(booking=self.booking, amount=1000, payment_status='verified', transaction_ref='concurrent-paid')
        self.session = ChatSession.objects.create(user=self.customer, assigned_admin=self.admin,
            is_admin_support=True, status='active_admin')
        self.upload_client = Client(); self.upload_client.force_login(self.admin)
        self.support_client = Client(); self.support_client.force_login(self.admin)

    def overlap(self, first):
        users_locked = {name: threading.Event() for name in ('delivery', 'support')}
        session_locked = threading.Event()
        second_attempting = threading.Event()

        def wait(event):
            if not event.wait(15):
                raise AssertionError('Concurrent request did not reach its expected lock boundary.')

        def run(name):
            close_old_connections()

            def observe(execute, sql, params, many, context):
                locking = sql.startswith('SELECT') and ('FOR UPDATE' in sql or 'FOR NO KEY UPDATE' in sql)
                user = locking and 'FROM "app_user"' in sql
                session = locking and 'FROM "app_chatsession"' in sql
                if session and name != first:
                    wait(session_locked)
                    second_attempting.set()
                result = execute(sql, params, many, context)
                if user:
                    users_locked[name].set()
                    wait(users_locked['support' if name == 'delivery' else 'delivery'])
                if session and name == first:
                    session_locked.set()
                    wait(second_attempting)
                return result

            try:
                with connection.execute_wrapper(observe):
                    if name == 'delivery':
                        return self.upload_client.post(reverse('admin_booking_design_upload', args=[self.booking.pk]),
                            {'design_image': _design_upload(), 'submission_id': uuid.uuid4().hex},
                            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                    return self.support_client.post(reverse('support_send'), {'session_id': self.session.pk,
                        'request_id': str(uuid.uuid4()), 'message': 'Here is an additional note.'})
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            delivery = pool.submit(run, 'delivery')
            support = pool.submit(run, 'support')
            self.assertEqual(delivery.result(timeout=35).status_code, 200)
            self.assertEqual(support.result(timeout=35).status_code, 200)
        self.assertEqual(ChatMessage.objects.filter(session=self.session).count(), 2)
        self.assertEqual(self.booking.design_deliveries.count(), 1)

    @skipUnlessDBFeature('has_select_for_no_key_update')
    def test_delivery_waits_for_support_send_without_deadlock(self):
        self.overlap('support')

    @skipUnlessDBFeature('has_select_for_no_key_update')
    def test_support_send_waits_for_delivery_without_deadlock(self):
        self.overlap('delivery')
