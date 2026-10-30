"""Two administrators cannot consume the same remaining design slot."""
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingDesignDelivery, Notification, Payment, User
from .test_design_delivery import TempMediaMixin, _design_upload


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
class DesignDeliveryConcurrencyTests(TempMediaMixin, TransactionTestCase):
    def test_concurrent_uploads_cannot_exceed_three_designs(self):
        admin = User.objects.create_user(username='concurrent-designer', role='admin')
        customer = User.objects.create_user(username='concurrent-customer', role='customer')
        booking = Booking.objects.create(user=customer, status='confirmed',
            event_date=timezone.localdate()+timedelta(days=20), event_time=time(10),
            event_type='Birthday', event_location='Venue', package_type='Package A', total_price=5000)
        Payment.objects.create(booking=booking,amount=1000,payment_status='verified',transaction_ref='concurrent-paid')
        for _ in range(2): BookingDesignDelivery.objects.create(booking=booking,image=_design_upload())
        clients = [Client(), Client()]
        for client in clients: client.force_login(admin)
        barrier = Barrier(2)
        url = reverse('admin_booking_design_upload',args=[booking.pk])

        def send(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = clients[index].post(url, {'design_image':_design_upload(),
                    'submission_id':f'concurrent-{index}'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send,range(2)))
        self.assertEqual(sorted(results),[200,400])
        self.assertEqual(booking.design_deliveries.count(),3)
        self.assertEqual(Notification.objects.filter(booking=booking,message__contains='design').count(),1)
