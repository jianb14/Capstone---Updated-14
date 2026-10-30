"""Admin queues, payment gates and AJAX writes share the existing booking rules."""
from datetime import time, timedelta
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingChangeRequest, BookingDesignDelivery, BookingStatusLog, Notification, Payment, User
from .test_design_delivery import TempMediaMixin, _design_upload

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class AdminBookingWorkspaceTests(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username='booking-team', role='admin')
        self.user = User.objects.create_user(username='booking-owner', first_name='Test', last_name='Customer', role='customer')
        self.client.force_login(self.admin)

    def booking(self, status='confirmed', paid=True, **updates):
        values = dict(user=self.user, event_date=timezone.localdate()+timedelta(days=20+Booking.objects.count()),
            event_time=time(10), event_end_time=time(13), event_type='Birthday', event_location='Long venue address',
            package_type='Package A', total_price=5000, status=status, design_theme='Butterfly', motto_text='Happy Birthday')
        values.update(updates)
        booking = Booking.objects.create(**values)
        if paid:
            Payment.objects.create(booking=booking, amount=1000, payment_status='verified', transaction_ref=f'paid-{booking.pk}')
        return booking

    def test_design_queue_counts_only_confirmed_verified_and_classifies_revisions(self):
        needed = self.booking()
        sent = self.booking()
        revision = self.booking()
        self.booking(paid=False)
        self.booking(status='pending_payment')
        self.booking(status='cancelled')
        BookingDesignDelivery.objects.create(booking=sent, image=_design_upload())
        BookingDesignDelivery.objects.create(booking=revision, image=_design_upload())
        BookingChangeRequest.objects.create(booking=revision, status='applied', proposed={'_design_changed': True},
            original={}, applied_at=timezone.now(), reason='Revised backdrop', original_total=5000, quoted_total=5000)
        response = self.client.get(reverse('admin_booking_list'), {'tab':'designs'})
        self.assertEqual(response.context['design_summary'], {'total':3, 'needed':1, 'revision':1, 'sent':1})
        for state, booking in [('needed',needed), ('revision',revision), ('sent',sent)]:
            response = self.client.get(reverse('admin_booking_list'), {'tab':'designs', 'design_status':state})
            self.assertEqual([b.pk for b in response.context['bookings']], [booking.pk])
        BookingDesignDelivery.objects.create(booking=revision, image=_design_upload())
        response = self.client.get(reverse('admin_booking_list'), {'tab':'designs', 'design_status':'sent'})
        self.assertEqual({b.pk for b in response.context['bookings']}, {sent.pk, revision.pk})

    def test_search_dates_page_sizes_empty_and_conflicts(self):
        first = self.booking(status='pending', paid=False)
        other = self.booking(event_date=first.event_date)
        for _ in range(8): self.booking(status='pending', paid=False)
        url = reverse('admin_booking_list')
        response = self.client.get(url)
        self.assertEqual(len(response.context['bookings']),8)
        response = self.client.get(url, {'search':f'#{first.pk}'})
        self.assertTrue(response.context['bookings'][0].has_conflict)
        response = self.client.get(url, {'search':'Test Customer', 'per_page':4})
        self.assertEqual(response.context['page'].paginator.count, 10)
        self.assertEqual(len(response.context['bookings']), 4)
        for search in ('9'*150, '\u00b2'):
            response = self.client.get(url, {'search':search}, **AJAX)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('<thead>', response.json()['html'])
        response = self.client.get(url, {'search':'Customer', 'per_page':4, 'page':2})
        self.assertEqual(len(response.context['bookings']),4)
        response = self.client.get(url, {'date_from':str(first.event_date), 'date_to':str(first.event_date)})
        self.assertEqual({b.pk for b in response.context['bookings']}, {first.pk, other.pk})
        response = self.client.get(url, {'date_from':'2099-02-02', 'date_to':'2099-01-01'}, **AJAX)
        self.assertIn('end date must be on or after',response.json()['html'])
        self.assertNotIn('<thead>',response.json()['html'])
        response = self.client.get(url, {'search':'<script>unmatched'}, **AJAX)
        self.assertNotIn('<thead>',response.json()['html'])
        self.assertNotIn('<script>unmatched',response.json()['html'])

    def test_details_render_system_history_and_removed_actors(self):
        booking = self.booking(status='expired', paid=False)
        removed_actor = User.objects.create_user(username='former-booking-admin', role='admin')
        BookingStatusLog.objects.create(booking=booking, new_status='pending_payment', changed_by=removed_actor,
            notes='Previously approved.')
        BookingStatusLog.objects.create(booking=booking, new_status='expired', changed_by=None,
            notes='Payment deadline expired automatically.')
        BookingStatusLog.objects.create(booking=booking, new_status='pending', changed_by=self.admin,
            notes='Recorded by an administrator.')
        removed_actor.delete()
        response = self.client.get(reverse('admin_booking_detail', args=[booking.pk]), **AJAX)
        self.assertEqual(response.status_code, 200)
        html = response.json()['html']
        self.assertEqual(html.count('System / removed account'), 2)
        self.assertIn('Payment deadline expired automatically.', html)
        self.assertIn(self.admin.username, html)

    def test_history_shows_more_from_eight_entries_and_caption_limit_is_visible(self):
        booking = self.booking()
        detail = reverse('admin_booking_detail', args=[booking.pk])
        for index in range(7):
            BookingStatusLog.objects.create(booking=booking, new_status='confirmed', notes=f'History {index}')
        html = self.client.get(detail, **AJAX).json()['html']
        self.assertNotIn('data-history-toggle', html)
        BookingStatusLog.objects.create(booking=booking, new_status='confirmed', notes='Eighth entry')
        html = self.client.get(detail, **AJAX).json()['html']
        self.assertIn('data-history-toggle', html)
        self.assertEqual(html.count('data-history-extra hidden'), 1)
        html = self.client.get(detail, {'section':'design'}, **AJAX).json()['html']
        self.assertIn('maxlength="255"', html)
        self.assertIn('data-caption-count', html)
        self.assertIn('0/255', html)

    def test_ajax_details_and_design_validation_replay_notification(self):
        booking = self.booking()
        url = reverse('admin_booking_detail', args=[booking.pk])
        response = self.client.get(url, **AJAX)
        self.assertContains(response,'Booking details')
        response = self.client.get(url, {'section':'design'}, **AJAX)
        self.assertIn('Happy Birthday',response.json()['html'])
        self.assertIn('Customer references',response.json()['html'])
        upload = reverse('admin_booking_design_upload',args=[booking.pk])
        response = self.client.post(upload, {'caption':'x'*256}, **AJAX)
        self.assertEqual(response.status_code,400)
        self.assertIn('design_image',response.json()['errors'])
        response = self.client.post(upload, {'design_image':_design_upload(), 'caption':'x'*256}, **AJAX)
        self.assertEqual(response.status_code,400)
        self.assertIn('caption',response.json()['errors'])
        data = {'design_image':_design_upload(), 'caption':'Final design', 'submission_id':'test-operation-1', 'design_revision':''}
        response = self.client.post(upload,data,**AJAX)
        self.assertEqual(response.status_code,200,response.content)
        response = self.client.post(upload, {'design_image':_design_upload(), 'submission_id':'test-operation-1'}, **AJAX)
        self.assertEqual(response.status_code,200)
        self.assertEqual(BookingDesignDelivery.objects.filter(booking=booking).count(),1)
        self.assertEqual(Notification.objects.filter(booking=booking,message__contains='design').count(),1)
        delivery = booking.design_deliveries.get()
        response = self.client.post(reverse('admin_booking_design_delete', args=[booking.pk,delivery.pk]), **AJAX)
        self.assertEqual(response.status_code,200)
        self.assertFalse(booking.design_deliveries.exists())

    def test_upload_checks_actual_image_contents_and_slot_limit(self):
        from PIL import Image
        booking = self.booking()
        url = reverse('admin_booking_design_upload',args=[booking.pk])
        gif = BytesIO(); Image.new('RGB',(8,8)).save(gif,format='GIF')
        for contents in (b'not an image',gif.getvalue(),_design_upload().read()[:45]):
            response = self.client.post(url, {'design_image':SimpleUploadedFile('design.png',contents,content_type='image/png')}, **AJAX)
            self.assertEqual(response.status_code,400)
            self.assertIn('design_image',response.json()['errors'])
        self.assertFalse(booking.design_deliveries.exists())
        for _ in range(3): BookingDesignDelivery.objects.create(booking=booking,image=_design_upload())
        response = self.client.post(url, {'design_image':_design_upload()}, **AJAX)
        self.assertEqual(response.status_code,400)
        self.assertEqual(booking.design_deliveries.count(),3)

    def test_logistics_fee_validation_returns_inline_errors_and_updates_total(self):
        booking = self.booking(logistics_fee=1000)
        url = reverse('admin_booking_logistics_override',args=[booking.pk])
        for value in ('NaN','Infinity','-1','100000000','0.001','invalid'):
            response = self.client.post(url, {'logistics_fee_override':value}, **AJAX)
            self.assertEqual(response.status_code,400)
            self.assertIn('logistics_fee_override',response.json()['errors'])
        response = self.client.post(url, {'logistics_fee_override':'1200'}, **AJAX)
        self.assertEqual(response.status_code,200)
        booking.refresh_from_db(); self.assertEqual(booking.total_price,5200)
        response = self.client.post(url, {'logistics_fee_override':''}, **AJAX)
        self.assertEqual(response.status_code,200)
        booking.refresh_from_db(); self.assertEqual(booking.total_price,5000)

    def test_unpaid_unapplied_pending_and_stale_revision_cannot_deliver(self):
        booking = self.booking(paid=False)
        url = reverse('admin_booking_design_upload',args=[booking.pk])
        for status, applied, amount in [('pending',True,1000), ('verified',False,1000), ('verified',True,0)]:
            payment = Payment.objects.create(booking=booking,payment_status=status,applied_to_booking=applied,amount=amount,transaction_ref=f'{status}-{applied}-{amount}')
            self.assertEqual(self.client.post(url, {'design_image':_design_upload()},**AJAX).status_code,400)
            payment.delete()
        Payment.objects.create(booking=booking,payment_status='verified',amount=1000,transaction_ref='paid')
        BookingChangeRequest.objects.create(booking=booking,status='applied',proposed={'_design_changed':True},original={},applied_at=timezone.now(),original_total=5000, quoted_total=5000)
        response = self.client.post(url, {'design_image':_design_upload(), 'design_revision':''},**AJAX)
        self.assertEqual(response.status_code,400)
        self.assertFalse(booking.design_deliveries.exists())

    def test_actions_have_state_guards_and_are_async(self):
        booking = self.booking(status='pending',paid=False)
        url = lambda action: reverse('admin_booking_action',args=[booking.pk,action])
        self.assertEqual(self.client.get(url('approve'),**AJAX).status_code,405)
        self.assertEqual(self.client.post(url('deny'), {'deny_reason':' '}, **AJAX).status_code,400)
        self.assertEqual(self.client.post(url('complete'),**AJAX).status_code,400)
        response = self.client.post(url('approve'), **AJAX)
        self.assertEqual(response.status_code,200,response.content)
        booking.refresh_from_db(); self.assertEqual(booking.status,'pending_payment')
        self.assertEqual(self.client.post(url('deny'),{'deny_reason':'Late denial'},**AJAX).status_code,400)
        self.assertEqual(self.client.post(url('approve'),**AJAX).status_code,400)
        booking.refresh_from_db(); self.assertEqual(booking.status,'pending_payment')

    def test_customer_cannot_access_queue_details_or_mutations_and_csrf_is_required(self):
        booking = self.booking()
        self.client.force_login(self.user)
        for url in (reverse('admin_booking_list'),reverse('admin_booking_detail',args=[booking.pk])):
            self.assertEqual(self.client.get(url, **AJAX).status_code,403)
        self.assertEqual(self.client.post(reverse('admin_booking_design_upload',args=[booking.pk]), {'design_image':_design_upload()}, **AJAX).status_code,403)
        from django.test import Client
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(reverse('admin_booking_design_upload',args=[booking.pk]), {'design_image':_design_upload()}, **AJAX).status_code,403)
