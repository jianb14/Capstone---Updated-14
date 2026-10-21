from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .booking_changes import (eligibility, issue_quote, prepare_proposal, process_changes,
    snapshot, verified_paid)
from .context_processors import _customer_notif_target_url, _admin_notif_target_url
from .models import (AdminNotification, Booking, BookingChangeRequest, BookingImage, BookingDesignDelivery, Notification,
    Package, Payment, ServiceChargeConfig, SiteSettings, User)
from .views.common import capture_booking_fee_policy, find_active_booking_conflicts, get_booking_form_availability


class BookingChangeTests(TestCase):
    def setUp(self):
        storage = override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'}, 'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        storage.enable();self.addCleanup(storage.disable)
        self.now = timezone.make_aware(datetime(2035, 1, 21, 10))
        clock = patch('django.utils.timezone.now', return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.user = User.objects.create_user(username='change-owner', role='customer')
        self.other = User.objects.create_user(username='change-other', role='customer')
        self.admin = User.objects.create_user(username='change-team', role='admin')
        self.site = SiteSettings.load()
        ServiceChargeConfig.objects.create(pk=1, amount=1000, shop_lat=14.414, shop_lng=120.982, per_km_rate=30)
        self.package = Package.objects.create(name='Package A', price=5000)
        Package.objects.create(name='Package B', price=7000)
        Package.objects.create(name='Package C', price=4000)
        self.booking = Booking.objects.create(user=self.user, event_date=self.now.date()+timedelta(days=10),
            event_time=time(7), event_end_time=time(10), event_end_date=self.now.date()+timedelta(days=10),
            event_type='Birthday', event_location='Molino Bacoor Cavite venue', event_lat='14.414000', event_lng='120.982000',
            package_type='Package A', total_price=6000, logistics_fee=1000, duration_minutes=180,
            design_theme='Princess', color_palette='Pink, Gold', motto_text='Happy Birthday', status='confirmed',
            special_requests='Bring balloons.\n(End Time: 10:00)')
        capture_booking_fee_policy(self.booking)
        self.booking.save()
        self.original_payment = Payment.objects.create(booking=self.booking, amount=6000, payment_method='gcash',
            payment_status='verified', transaction_ref='original-payment', verified_by=self.admin, received_at=self.now)
        self.booking.payment_status='paid'
        self.booking.save()
        self.client.force_login(self.user)

    def data(self, **updates):
        data = {'event_date':self.booking.event_date.isoformat(), 'start_time':'07:00', 'end_time':'10:00',
            'event_type':'Birthday', 'event_location':self.booking.event_location, 'event_lat':str(self.booking.event_lat),
            'event_lng':str(self.booking.event_lng), 'package_type':'Package A', 'design_theme':'Princess',
            'color_palette':'Pink, Gold', 'motto_text':'Happy Birthday', 'special_requests':'Bring balloons.',
            'change_reason':'We need to update our event details.', 'total_price':'0.01'}
        data.update(updates)
        return data

    def submit(self, **updates):
        response = self.client.post(reverse('request_booking_change', args=[self.booking.pk]), self.data(**updates), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['success'])
        return BookingChangeRequest.objects.filter(booking=self.booking).order_by('-pk').first()

    def quote(self, change, **updates):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_booking_change_action', args=[self.booking.pk, change.pk, 'quote']), updates)
        change.refresh_from_db()
        return response

    def accept(self, change, **updates):
        self.client.force_login(self.user)
        response = self.client.post(reverse('customer_booking_change_action', args=[self.booking.pk, change.pk, 'accept']), {'accept_quote':'on', **updates})
        change.refresh_from_db()
        return response

    def proof(self, change, **updates):
        buffer=BytesIO(); Image.new('RGB',(3,3),'pink').save(buffer, format='PNG')
        data={'gcash_sender_name':'Customer', 'gcash_reference_number':'1234567890123', 'refund_ack':'on',
            'receipt_image':SimpleUploadedFile('receipt.png',buffer.getvalue(),content_type='image/png')}
        data.update(updates)
        return self.client.post(reverse('booking_change_payment', args=[self.booking.pk, change.pk]), data)

    def test_request_preserves_booking_payments_and_price(self):
        before=snapshot(self.booking)
        change=self.submit(package_type='Package B', end_time='12:00')
        self.booking.refresh_from_db();self.original_payment.refresh_from_db()
        self.assertEqual(snapshot(self.booking), before)
        self.assertEqual(self.original_payment.amount,6000)
        self.assertEqual(change.quoted_total,9000)
        self.assertEqual(change.status,'pending_review')

    def test_same_price_applies_only_after_admin_quote_and_customer_accept(self):
        change=self.submit(motto_text='Happy 18th Birthday')
        self.quote(change)
        self.assertEqual(change.status,'quoted')
        self.booking.refresh_from_db();self.assertEqual(self.booking.motto_text,'Happy Birthday')
        self.accept(change)
        self.assertEqual(change.status,'applied')
        self.booking.refresh_from_db();self.assertEqual(self.booking.motto_text,'Happy 18th Birthday')
        self.assertEqual(Payment.objects.count(),1)

    def test_upgrade_waits_for_additional_payment_verification(self):
        change=self.submit(package_type='Package B')
        self.quote(change);self.assertEqual(change.additional_due,2000)
        self.accept(change);self.assertEqual(change.status,'awaiting_payment')
        self.assertEqual(self.proof(change).status_code,302)
        payment=change.payments.get();self.assertEqual(payment.amount,2000)
        self.assertFalse(payment.applied_to_booking)
        self.booking.refresh_from_db();self.assertEqual(self.booking.package_type,'Package A')
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action',args=[payment.pk,'verify']))
        change.refresh_from_db();self.booking.refresh_from_db();payment.refresh_from_db()
        self.assertEqual(change.status,'applied')
        self.assertEqual(self.booking.total_price,8000)
        self.assertEqual(self.booking.package_type,'Package B')
        self.assertEqual(verified_paid(self.booking),8000)
        self.assertTrue(payment.applied_to_booking)
        self.assertEqual(self.booking.payment_status,'paid')

    def test_partial_payment_upgrade_charges_only_difference(self):
        self.original_payment.amount=1200;self.original_payment.save()
        change=self.submit(package_type='Package B');self.quote(change)
        self.assertEqual(change.additional_due,2000)
        self.accept(change);self.proof(change)
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action',args=[change.payments.get().pk,'verify']))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price-verified_paid(self.booking),4800)

    def test_unpaid_approved_quote_uses_initial_payment_after_apply(self):
        self.original_payment.delete();self.booking.status='pending_payment'
        self.booking.payment_due_at=self.now+timedelta(hours=12);self.booking.save()
        change=self.submit(package_type='Package B');self.quote(change)
        self.assertEqual(change.additional_due,0)
        self.accept(change);self.booking.refresh_from_db()
        self.assertEqual(change.status,'applied');self.assertEqual(self.booking.total_price,8000)
        self.assertEqual(self.booking.payment_due_at,self.now+timedelta(hours=12))
        self.assertEqual(self.booking.status,'pending_payment')

    def test_single_active_request(self):
        self.submit(motto_text='New Text')
        response=self.client.post(reverse('request_booking_change',args=[self.booking.pk]),self.data(package_type='Package B'),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,400)
        self.assertEqual(BookingChangeRequest.objects.count(),1)

    def test_cutoff_is_enforced_and_configurable(self):
        self.booking.event_date=self.now.date()+timedelta(days=1);self.booking.save()
        self.assertFalse(eligibility(self.booking)[0])
        self.site.booking_change_cutoff_hours=12;self.site.save()
        self.assertTrue(eligibility(self.booking)[0])

    def test_pending_proof_prevents_submission(self):
        Payment.objects.create(booking=self.booking,amount=100,payment_method='gcash',payment_status='pending',transaction_ref='unverified')
        response=self.client.post(reverse('request_booking_change',args=[self.booking.pk]),self.data(motto_text='New text'),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,400)
        self.assertIn('being verified',response.json()['message'])

    def test_saved_package_price_is_not_repriced_for_notes_change(self):
        self.package.price=9999;self.package.save()
        self.site.booking_overtime_rate=999;self.site.save()
        change=self.submit(motto_text='New Text')
        self.assertEqual(change.quoted_total,6000)

    def test_downgrade_requires_manual_review_notes_and_acknowledgment(self):
        change=self.submit(package_type='Package C')
        self.quote(change);self.assertEqual(change.status,'pending_review')
        self.quote(change,admin_notes='Difference handled directly under policy.',downgrade_ack='on')
        self.assertEqual(change.status,'quoted')
        self.accept(change,accept_nonrefundable_excess='on');self.booking.refresh_from_db()
        self.assertEqual(change.status,'applied')
        self.assertEqual(self.booking.total_price,5000)
        self.assertEqual(self.original_payment.amount,6000)
        self.assertEqual(Payment.objects.count(),1)

    def test_quote_holds_new_slot_while_original_remains_reserved(self):
        day=self.booking.event_date+timedelta(days=1)
        change=self.submit(event_date=day.isoformat(),package_type='Package B');self.quote(change)
        other=Booking(user=self.other,event_date=day,event_time=time(8),event_end_time=time(11),total_price=6000)
        self.assertTrue(find_active_booking_conflicts(other))
        original=Booking(user=self.other,event_date=self.booking.event_date,event_time=time(8),event_end_time=time(11),total_price=6000)
        self.assertTrue(find_active_booking_conflicts(original))
        records=get_booking_form_availability()['rangeRecords']
        self.assertTrue(any(r.get('temporaryHold') and r['date']==day.isoformat() for r in records))

    def test_expired_quote_releases_hold_without_changing_original(self):
        change=self.submit(event_date=(self.booking.event_date+timedelta(days=1)).isoformat())
        self.quote(change);before=snapshot(self.booking)
        process_changes(change.expires_at+timedelta(seconds=1));change.refresh_from_db();self.booking.refresh_from_db()
        self.assertEqual(change.status,'expired');self.assertIsNone(change.hold_start)
        self.assertEqual(snapshot(self.booking),before)

    def test_submitted_proof_preserves_hold_after_due_and_warns_once(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        for _ in range(2):process_changes(change.expires_at+timedelta(minutes=1))
        change.refresh_from_db();self.assertEqual(change.status,'awaiting_payment')
        self.assertIsNotNone(change.hold_start)
        self.assertEqual(AdminNotification.objects.filter(message__contains='Verify urgently').count(),1)

    def test_other_customer_cannot_access_or_accept_or_pay(self):
        change=self.submit(package_type='Package B');self.quote(change)
        self.client.force_login(self.other)
        for name,args in [('request_booking_change',[self.booking.pk]),('booking_change_payment',[self.booking.pk,change.pk]),('customer_booking_change_action',[self.booking.pk,change.pk,'accept'])]:
            response=self.client.get(reverse(name,args=args)) if name != 'customer_booking_change_action' else self.client.post(reverse(name,args=args),{'accept_quote':'on'})
            self.assertIn(response.status_code,(403,404))

    def test_customer_cannot_issue_team_quote(self):
        change=self.submit(motto_text='New text')
        response=self.client.post(reverse('admin_booking_change_action',args=[self.booking.pk,change.pk,'quote']))
        self.assertEqual(response.status_code,403)

    def test_quote_and_original_details_render_in_customer_and_admin(self):
        change=self.submit(package_type='Package B',end_time='12:00');self.quote(change)
        self.client.force_login(self.user)
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        for text in ('Booking change request','Original booking','Requested change','Accept Final Quote','2 hr(s) beyond the 3-hour package','Price difference'):
            self.assertContains(response,text)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('admin_booking_change_detail',args=[change.pk])),'Approve &amp; Send Final Quote',count=0)

    def test_off_page_approved_edit_link_opens_request_form(self):
        response=self.client.get(reverse('customer_profile'),{'open_edit':self.booking.pk,'search':'missing'})
        self.assertContains(response,f'booking-data-{self.booking.pk}')
        self.assertContains(response,'class="raw-change-mode">1')

    def test_notification_links_go_to_booking_instead_of_review_or_payment_history(self):
        change=self.submit(package_type='Package B');self.quote(change)
        notif=Notification.objects.filter(booking=self.booking).last()
        self.assertIn(f'booking_id={self.booking.pk}',_customer_notif_target_url(notif))
        self.assertEqual(_admin_notif_target_url('notification','Booking change request needs review',self.booking),f"{reverse('admin_booking_list')}?tab=requests&booking_id={self.booking.pk}")

    def test_rejection_and_withdrawal_keep_original(self):
        change=self.submit(package_type='Package B');before=snapshot(self.booking)
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_booking_change_action',args=[self.booking.pk,change.pk,'reject']),{'admin_notes':'Crew not available'})
        change.refresh_from_db();self.assertEqual(change.status,'rejected')
        self.booking.refresh_from_db();self.assertEqual(snapshot(self.booking),before)
        self.client.force_login(self.user);change=self.submit(motto_text='New Text')
        self.client.post(reverse('customer_booking_change_action',args=[self.booking.pk,change.pk,'withdraw']))
        change.refresh_from_db();self.assertEqual(change.status,'withdrawn')

    def test_unapplied_verified_funds_do_not_change_original_balance_or_state(self):
        change=self.submit(package_type='Package B')
        Payment.objects.create(booking=self.booking,change_request=change,applied_to_booking=False,amount=2000,payment_method='gcash',payment_status='verified',transaction_ref='unapplied')
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertEqual(response.context['total_verified_paid'],6000)
        self.assertEqual(response.context['remaining_balance'],0)

    @override_settings(PAYMONGO_SECRET_KEY='test')
    @patch('app.views.changes.create_paymongo_checkout_session')
    def test_online_change_checkout_uses_server_quote_not_posted_amount(self, checkout):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change)
        checkout.return_value={'data':{'id':'cs_change','attributes':{'checkout_url':'https://checkout.paymongo.com/change'}}}
        response=self.client.post(reverse('booking_change_payment',args=[self.booking.pk,change.pk]),{'method':'paymongo','refund_ack':'on','amount':'1'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(checkout.call_args.kwargs['amount'],200000)
        self.assertEqual(change.payments.get().amount,2000)

    def test_payment_rejection_does_not_modify_original_booking(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        before=snapshot(self.booking)
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action',args=[change.payments.get().pk,'reject']),{'admin_notes':'Receipt does not match'})
        self.booking.refresh_from_db();self.assertEqual(snapshot(self.booking),before)
        self.assertEqual(change.payments.get().payment_status,'rejected')

    def test_late_change_payment_is_recorded_without_applying_or_crediting_original(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        payment=change.payments.get();payment.received_at=change.expires_at+timedelta(minutes=1);payment.save()
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action',args=[payment.pk,'verify']))
        self.booking.refresh_from_db();change.refresh_from_db();payment.refresh_from_db()
        self.assertEqual(change.status,'manual_review');self.assertEqual(payment.payment_status,'verified')
        self.assertFalse(payment.applied_to_booking);self.assertEqual(self.booking.total_price,6000)

    def test_duplicate_verification_does_not_apply_or_charge_twice(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        self.client.force_login(self.admin)
        for _ in range(2):self.client.post(reverse('admin_payment_action',args=[change.payments.get().pk,'verify']))
        self.booking.refresh_from_db();self.assertEqual(self.booking.total_price,8000)
        self.assertEqual(verified_paid(self.booking),8000)
        self.assertEqual(self.booking.status_logs.filter(notes__contains='Customer-accepted changes applied').count(),1)

    def test_stale_original_cannot_be_applied(self):
        change=self.submit(package_type='Package B');self.quote(change)
        self.booking.total_price=6100;self.booking.save()
        self.accept(change);change.refresh_from_db();self.booking.refresh_from_db()
        self.assertEqual(change.status,'quoted');self.assertEqual(self.booking.total_price,6100)

    def test_additional_payment_cannot_be_withdrawn_without_resolution(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        self.client.post(reverse('customer_booking_change_action',args=[self.booking.pk,change.pk,'withdraw']))
        change.refresh_from_db();self.assertEqual(change.status,'awaiting_payment')

    def test_quote_acceptance_is_required_and_repeat_safe(self):
        change=self.submit(motto_text='New Text');self.quote(change)
        self.client.force_login(self.user)
        self.client.post(reverse('customer_booking_change_action',args=[self.booking.pk,change.pk,'accept']))
        change.refresh_from_db();self.assertEqual(change.status,'quoted')
        self.accept(change);self.accept(change);self.assertEqual(change.status,'applied')

    def test_old_unpaid_quote_is_reissued_if_original_payment_was_verified(self):
        self.original_payment.delete();self.booking.status='pending_payment';self.booking.save()
        change=self.submit(package_type='Package B');self.quote(change)
        Payment.objects.create(booking=self.booking,amount=1200,payment_status='verified',payment_method='gcash',transaction_ref='paid-after-quote',verified_by=self.admin)
        self.accept(change);self.assertEqual(change.status,'pending_review')
        self.quote(change);self.assertEqual(change.additional_due,2000)

    def test_new_schedule_conflict_between_submission_and_review_blocks_quote(self):
        day=self.booking.event_date+timedelta(days=1)
        change=self.submit(event_date=day.isoformat())
        Booking.objects.create(user=self.other,event_date=day,event_time=time(8),event_end_time=time(11),total_price=6000,status='confirmed')
        self.quote(change);self.assertEqual(change.status,'pending_review')

    def test_held_slot_blocks_new_creation_and_pending_booking_approval(self):
        day=self.booking.event_date+timedelta(days=1)
        change=self.submit(event_date=day.isoformat());self.quote(change)
        self.client.force_login(self.other)
        created=self.client.post(reverse('create_booking'),self.data(event_date=day.isoformat(),start_time='08:00',end_time='11:00',total_price='6000'),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(created.json()['success'])
        pending=Booking.objects.create(user=self.other,event_date=day,event_time=time(8),event_end_time=time(11),total_price=6000,status='pending')
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_booking_action',args=[pending.pk,'approve']))
        pending.refresh_from_db();self.assertEqual(pending.status,'pending')

    def test_invalid_or_missing_venue_pin_cannot_reuse_old_pin_for_new_address(self):
        for lat,lng in [('', ''),('NaN','120'),('91','120')]:
            with self.assertRaises(ValidationError):
                prepare_proposal(self.booking,self.data(event_location='New venue Baguio city',event_lat=lat,event_lng=lng))

    def test_same_selection_and_old_overtime_rate_stay_frozen_after_rate_change(self):
        self.booking.event_end_time=time(12);self.booking.duration_minutes=300;self.booking.overtime_hours=2
        self.booking.overtime_fee=1000;self.booking.total_price=7000;capture_booking_fee_policy(self.booking);self.booking.save()
        self.site.booking_overtime_rate=999;self.site.save()
        proposed=prepare_proposal(self.booking,self.data(end_time='12:00',motto_text='New text'))
        self.assertEqual(proposed.overtime_fee,1000);self.assertEqual(proposed.total_price,7000)

    def test_design_preference_change_marks_previous_delivery_and_requires_revision(self):
        delivery=BookingDesignDelivery.objects.create(booking=self.booking,image='delivered.png')
        BookingDesignDelivery.objects.filter(pk=delivery.pk).update(uploaded_at=self.now-timedelta(days=1))
        change=self.submit(motto_text='New backdrop');self.quote(change);self.accept(change)
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertContains(response,'Design Revision Pending')
        self.assertTrue(response.context['lifecycle']['design_revision_pending'])
        design=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]),{'section':'design'})
        self.assertContains(design,'Previous design')
        BookingDesignDelivery.objects.filter(pk=delivery.pk).update(uploaded_at=self.now+timedelta(minutes=1))
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertFalse(response.context['lifecycle']['design_revision_pending'])

    def test_request_reference_images_are_only_changed_when_applied(self):
        existing=BookingImage.objects.create(booking=self.booking,image='original.png')
        buffer=BytesIO();Image.new('RGB',(5,5)).save(buffer,format='PNG')
        change=self.submit(motto_text='New text',**{'remove_images[]':[str(existing.pk)],'reference_images':SimpleUploadedFile('new.png',buffer.getvalue(),content_type='image/png')})
        self.assertTrue(self.booking.images.filter(pk=existing.pk).exists())
        self.quote(change);self.accept(change)
        self.assertFalse(self.booking.images.filter(pk=existing.pk).exists())
        self.assertEqual(self.booking.images.count(),1)

    def test_manual_payment_resolution_closes_request_without_mutating_ledger(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        payment=change.payments.get();payment.received_at=change.expires_at+timedelta(minutes=1);payment.save()
        self.client.force_login(self.admin);self.client.post(reverse('admin_payment_action',args=[payment.pk,'verify']))
        self.client.post(reverse('admin_booking_change_action',args=[self.booking.pk,change.pk,'resolve']),{'admin_notes':'Customer contacted; separate funds resolved directly.','resolution_ack':'on'})
        change.refresh_from_db();payment.refresh_from_db();self.booking.refresh_from_db()
        self.assertEqual(change.status,'withdrawn');self.assertEqual(payment.payment_status,'verified')
        self.assertFalse(payment.applied_to_booking);self.assertEqual(self.booking.total_price,6000)

    def test_admin_cutoff_setting_is_saved(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_site_settings'),{'site_name':'Balloorina','booking_change_cutoff_hours':'72'})
        self.site.refresh_from_db();self.assertEqual(self.site.booking_change_cutoff_hours,72)

    def test_upgrade_does_not_show_admin_or_customer_nonrefund_checkbox(self):
        change=self.submit(package_type='Package B')
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_change_detail',args=[change.pk]))
        self.assertNotContains(response,'name="downgrade_ack"')
        self.assertContains(response,'Message to customer (Optional)')
        self.assertContains(response,'Verified payments already credited')
        self.assertContains(response,'Additional payment for this change')
        self.assertEqual(response.context['change_extra_payment'],2000)
        self.quote(change,downgrade_ack='on')
        self.assertFalse(change.downgrade_acknowledged)
        self.client.force_login(self.user)
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertNotContains(response,'name="accept_nonrefundable_excess"')
        self.assertNotContains(response,'will not be refunded')
        self.assertContains(response,'The previous payment stays credited.')

    def test_customer_must_explicitly_accept_nonrefundable_excess(self):
        change=self.submit(package_type='Package C')
        self.quote(change,admin_notes='The excess PHP 1,000 is non-refundable under the payment policy.',downgrade_ack='on')
        self.client.force_login(self.user)
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertContains(response,'name="accept_nonrefundable_excess"')
        self.assertContains(response,'excess ₱1,000.00 from my previous payment will not be refunded')
        self.assertNotContains(response,'No automatic refund or credit will be issued.')
        self.accept(change)
        self.assertEqual(change.status,'quoted')
        self.booking.refresh_from_db();self.assertEqual(self.booking.total_price,6000)
        self.accept(change,accept_nonrefundable_excess='on')
        self.assertEqual(change.status,'applied')
        self.assertIn('customer_nonrefund_accepted_at',change.quote)
        self.assertEqual(self.booking.status_logs.filter(notes__contains='Customer accepted the non-refundable excess').count(),1)

    def test_deposit_downgrade_without_excess_has_no_refund_acknowledgments(self):
        self.original_payment.amount=1200;self.original_payment.save()
        change=self.submit(package_type='Package C')
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_change_detail',args=[change.pk]))
        self.assertNotContains(response,'name="downgrade_ack"')
        self.assertEqual(response.context['change_excess_payment'],0)
        self.quote(change)
        self.assertEqual(change.status,'quoted')
        self.assertFalse(change.downgrade_acknowledged)
        self.client.force_login(self.user)
        response=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertNotContains(response,'name="accept_nonrefundable_excess"')
        self.assertEqual(response.context['change_balance_after_extra'],3800)
        self.accept(change);self.assertEqual(change.status,'applied')

    def test_admin_nonrefund_ack_is_shown_only_for_actual_excess(self):
        change=self.submit(package_type='Package C')
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_change_detail',args=[change.pk]))
        self.assertContains(response,'name="downgrade_ack" required')
        self.assertContains(response,'Excess payment: ₱1,000.00')
        self.assertContains(response,'Message to customer (Required)')
        self.assertContains(response,'I have explained the non-refundable excess')
        self.quote(change,admin_notes='Non-refundable excess explained.')
        self.assertEqual(change.status,'pending_review')

    def test_payment_after_quote_requires_updated_excess_terms(self):
        self.original_payment.amount=1200;self.original_payment.save()
        change=self.submit(package_type='Package C');self.quote(change)
        self.assertEqual(Decimal(change.quote['non_refundable_excess']),0)
        Payment.objects.create(booking=self.booking,amount=4800,payment_status='verified',payment_method='gcash',transaction_ref='balance-after-downgrade',verified_by=self.admin)
        self.accept(change,accept_nonrefundable_excess='on')
        self.assertEqual(change.status,'pending_review');self.assertIsNone(change.hold_start)
        self.assertIsNone(change.expires_at)
        self.booking.refresh_from_db();self.assertEqual(self.booking.total_price,6000)
        self.quote(change,admin_notes='New excess PHP 1,000 explained.',downgrade_ack='on')
        self.accept(change)
        self.assertEqual(change.status,'quoted')

    def test_preexisting_downgrade_quote_needs_explicitly_reviewed_excess_terms(self):
        change=self.submit(package_type='Package C');self.quote(change,admin_notes='Old handling.',downgrade_ack='on')
        change.quote.pop('non_refundable_excess');change.save()
        self.accept(change,accept_nonrefundable_excess='on')
        self.assertEqual(change.status,'pending_review')

    def test_price_increase_keeps_existing_payment_and_charges_only_difference(self):
        change=self.submit(package_type='Package B');self.quote(change)
        self.assertEqual(change.additional_due,2000)
        self.assertEqual(change.original_total,6000);self.assertEqual(change.quoted_total,8000)
        self.accept(change);self.proof(change)
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action',args=[change.payments.get().pk,'verify']))
        self.booking.refresh_from_db();self.original_payment.refresh_from_db()
        self.assertEqual(self.original_payment.amount,6000)
        self.assertEqual(verified_paid(self.booking),8000)
        self.assertEqual(self.booking.total_price,8000)


    def test_expired_hold_is_not_advertised_before_worker_runs(self):
        day=self.booking.event_date+timedelta(days=1)
        change=self.submit(event_date=day.isoformat());self.quote(change)
        with patch('django.utils.timezone.now',return_value=change.expires_at+timedelta(seconds=1)):
            rows=get_booking_form_availability()['rangeRecords']
            self.assertFalse(any(row.get('temporaryHold') for row in rows))
            candidate=Booking(user=self.other,event_date=day,event_time=time(8),event_end_time=time(11),total_price=6000)
            self.assertFalse(find_active_booking_conflicts(candidate))

    def test_unreviewed_request_closes_at_event_start_without_expiring_confirmed_booking(self):
        from .booking_lifecycle import event_start_at
        change=self.submit(motto_text='New text')
        process_changes(event_start_at(self.booking))
        change.refresh_from_db();self.booking.refresh_from_db()
        self.assertEqual(change.status,'expired');self.assertEqual(self.booking.status,'confirmed')

    def test_payment_link_preserves_request_history_without_breaking_booking_cascade(self):
        from django.db.models.deletion import RestrictedError
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        with self.assertRaises(RestrictedError):change.delete()
        self.assertEqual(Payment.objects.filter(booking=self.booking).count(),2)
        # Existing account/booking deletion must still collect the entire graph.
        pk=self.booking.pk;self.booking.delete()
        self.assertFalse(Payment.objects.filter(booking_id=pk).exists())

    def test_blocked_date_cannot_replace_a_live_quote_hold(self):
        from .models import BlockedDate
        day=self.booking.event_date+timedelta(days=1)
        change=self.submit(event_date=day.isoformat());self.quote(change)
        self.client.post(reverse('admin_blocked_date_create'),{'date':day.isoformat(),'confirm_conflicts':'1'})
        self.assertFalse(BlockedDate.objects.filter(date=day).exists())

    def test_payment_verification_after_event_start_requires_manual_resolution(self):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change);self.proof(change)
        self.client.force_login(self.admin)
        from .booking_lifecycle import event_start_at
        with patch('django.utils.timezone.now',return_value=event_start_at(self.booking)+timedelta(minutes=1)):
            self.client.post(reverse('admin_payment_action',args=[change.payments.get().pk,'verify']))
        change.refresh_from_db();self.booking.refresh_from_db()
        self.assertEqual(change.status,'manual_review');self.assertEqual(self.booking.package_type,'Package A')

    @override_settings(PAYMONGO_SECRET_KEY='test')
    @patch('app.views.changes.create_paymongo_checkout_session')
    def test_failed_online_checkout_can_be_retried(self, checkout):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change)
        Payment.objects.create(booking=self.booking,change_request=change,applied_to_booking=False,payment_type='change_balance',amount=2000,
            payment_method='paymongo_gcash',payment_status='pending',transaction_ref='failed-checkout',paymongo_checkout_session_id='cs_failed',
            paymongo_checkout_url='https://checkout.paymongo.com/failed',notes='PayMongo checkout cancelled — did not complete. Customer may retry with a new checkout.')
        checkout.return_value={'data':{'id':'cs_retry','attributes':{'checkout_url':'https://checkout.paymongo.com/retry'}}}
        response=self.client.post(reverse('booking_change_payment',args=[self.booking.pk,change.pk]),{'method':'paymongo','refund_ack':'on'})
        self.assertEqual(response.url,'https://checkout.paymongo.com/retry')
        self.assertIn(f'change_request={change.pk}',checkout.call_args.kwargs['success_url'])

    @patch('app.views.payments.retrieve_paymongo_checkout_session')
    def test_normal_provider_return_does_not_refresh_an_unrelated_change_checkout(self, retrieve):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change)
        Payment.objects.create(booking=self.booking,change_request=change,applied_to_booking=False,amount=2000,
            payment_method='paymongo_gcash',payment_status='pending',transaction_ref='change-checkout',paymongo_checkout_session_id='cs_change')
        self.client.get(reverse('paymongo_success',args=[self.booking.pk]))
        retrieve.assert_not_called()

    @patch('app.views.payments.retrieve_paymongo_checkout_session')
    def test_provider_return_for_change_matches_only_its_checkout(self, retrieve):
        change=self.submit(package_type='Package B');self.quote(change);self.accept(change)
        Payment.objects.create(booking=self.booking,change_request=change,applied_to_booking=False,amount=2000,
            payment_method='paymongo_gcash',payment_status='pending',transaction_ref='change-checkout',paymongo_checkout_session_id='cs_change')
        Payment.objects.create(booking=self.booking,amount=100,payment_method='paymongo_gcash',payment_status='pending',
            transaction_ref='original-checkout',paymongo_checkout_session_id='cs_original')
        retrieve.return_value={'data':{'attributes':{'status':'paid','payments':[{'id':'pay_change'}]}}}
        response=self.client.get(reverse('paymongo_success',args=[self.booking.pk]),{'change_request':change.pk})
        retrieve.assert_called_once_with('cs_change')
        self.assertEqual(response.url,reverse('booking_change_payment',args=[self.booking.pk,change.pk]))
        payment=change.payments.get();self.assertEqual(payment.paymongo_payment_id,'pay_change')
        self.assertIsNotNone(payment.received_at)


class BookingChangeConcurrencyTests(TransactionTestCase):
    def test_concurrent_quotes_cannot_hold_the_same_schedule(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        from .booking_changes import schedule_atomic
        SiteSettings.load()
        admin=User.objects.create_user(username='concurrent-change-admin',role='admin')
        owner=User.objects.create_user(username='concurrent-change-owner',role='customer')
        day=timezone.localdate()+timedelta(days=20)
        changes=[]
        for offset in (0,1):
            booking=Booking.objects.create(user=owner,event_date=day+timedelta(days=offset),event_time=time(7),event_end_time=time(10),total_price=6000,status='confirmed')
            proposed=snapshot(booking);proposed['event_date']=(day+timedelta(days=2)).isoformat()
            changes.append(BookingChangeRequest.objects.create(booking=booking,reason='Move our event date',original=snapshot(booking),proposed=proposed,original_total=6000,quoted_total=6000))
        barrier=Barrier(2)
        def run(pk):
            try:
                barrier.wait(timeout=10)
                @schedule_atomic
                def quote():
                    change=BookingChangeRequest.objects.select_related('booking').get(pk=pk)
                    issue_quote(change,admin)
                try:quote();return True
                except ValidationError:return False
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[change.pk for change in changes]))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(BookingChangeRequest.objects.filter(status='quoted').count(),1)
