"""End-to-end invariants for manual QR payments, without live financial calls."""
from datetime import time, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, GCashConfig, Notification, Payment, User


def png(name='proof.png'):
    stream = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(stream, format='PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class GCashQRTests(TestCase):
    def setUp(self):
        self.private = TemporaryDirectory()
        self.addCleanup(self.private.cleanup)
        storage = override_settings(PAYMENT_PROOF_ROOT=self.private.name, PAYMENT_PROOF_USE_CLOUDINARY=False)
        storage.enable()
        self.addCleanup(storage.disable)
        self.user = User.objects.create_user(username='qr-owner', role='customer')
        self.other = User.objects.create_user(username='qr-other', role='customer')
        self.admin = User.objects.create_user(username='qr-admin', role='admin')
        self.config = GCashConfig.objects.create(gcash_name='Balloorina Merchant', qr_code_image=png('merchant.png'))
        self.booking = Booking.objects.create(user=self.user, status='pending_payment', total_price=6000,
            event_date=timezone.localdate()+timedelta(days=30), event_time=time(10), event_type='Birthday',
            event_location='Venue', payment_due_at=timezone.now()+timedelta(hours=24))
        self.client.force_login(self.user)

    def payload(self, **updates):
        from .payment_forms import recipient_token
        data = {'gcash_reference_number':'1234567890123', 'gcash_sender_name':'Customer',
            'recipient_token':recipient_token(self.config),
            'gcash_paid_at':timezone.localtime().strftime('%Y-%m-%dT%H:%M'), 'payment_option':'downpayment',
            'amount':'1200.00', 'refund_ack':'on', 'receipt_image':png()}
        data.update(updates)
        return data

    def submit(self, booking=None, **updates):
        return self.client.post(reverse('submit_payment', args=[(booking or self.booking).pk]), self.payload(**updates))

    def test_customer_page_uses_configured_qr_without_paymongo_credentials(self):
        with override_settings(PAYMONGO_SECRET_KEY=''):
            response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertContains(response, 'Balloorina Merchant')
        self.assertContains(response, 'Download QR')
        self.assertContains(response, 'name="receipt_image"')
        self.assertContains(response, reverse('submit_payment', args=[self.booking.pk]))
        self.assertNotContains(response, 'GCash via PayMongo')
        self.assertNotContains(response, reverse('create_paymongo_checkout', args=[self.booking.pk]))

    def test_missing_qr_disables_form_and_submission(self):
        self.config.qr_code_image = ''
        self.config.save()
        response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertContains(response, 'Payment Unavailable')
        self.assertNotContains(response, 'name="receipt_image"')
        self.submit()
        self.assertFalse(Payment.objects.exists())

    def test_proof_is_pending_with_recipient_snapshot_and_private_storage(self):
        response = self.submit()
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, 1200)
        self.assertEqual(payment.payment_status, 'pending')
        self.assertEqual(payment.gcash_reference_key, '1234567890123')
        self.assertEqual(payment.gcash_recipient_name, 'Balloorina Merchant')
        self.assertIsNotNone(payment.gcash_paid_at)
        self.assertTrue(payment.receipt_image.name.startswith('private/'))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')
        self.config.gcash_name = 'Changed recipient'
        self.config.save()
        payment.refresh_from_db()
        self.assertEqual(payment.gcash_recipient_name, 'Balloorina Merchant')

    def test_required_proof_fields_and_invalid_images_cannot_create_payments(self):
        cases = [{'receipt_image':None}, {'gcash_reference_number':''}, {'gcash_sender_name':''},
            {'gcash_paid_at':''}, {'gcash_paid_at':(timezone.now()+timedelta(days=1)).isoformat()},
            {'receipt_image':SimpleUploadedFile('fake.png', b'<script>bad</script>', content_type='image/png')},
            {'receipt_image':SimpleUploadedFile('proof.svg', b'<svg/>', content_type='image/svg+xml')}]
        for updates in cases:
            with self.subTest(fields=list(updates)):
                data = self.payload(**updates)
                if data['receipt_image'] is None:
                    data.pop('receipt_image')
                self.client.post(reverse('submit_payment', args=[self.booking.pk]), data)
                self.assertFalse(Payment.objects.exists())

    def test_manipulated_amount_and_nonfinite_values_cannot_create_payments(self):
        for amount in ('1', 'NaN', 'Infinity', '-10', '1200.001', '6001'):
            with self.subTest(amount=amount):
                self.submit(amount=amount)
                self.assertFalse(Payment.objects.exists())

    def test_customer_cannot_pay_or_read_another_booking(self):
        self.client.force_login(self.other)
        self.assertEqual(self.submit().status_code, 404)
        self.assertEqual(self.client.get(reverse('payment_page', args=[self.booking.pk])).status_code, 404)

    def test_duplicate_reference_across_bookings_is_rejected_and_database_unique(self):
        self.submit()
        other_booking = Booking.objects.create(user=self.user, status='pending_payment', total_price=6000,
            event_date=timezone.localdate()+timedelta(days=35), event_time=time(10), event_type='Birthday',
            event_location='Other venue', payment_due_at=timezone.now()+timedelta(hours=24))
        self.submit(other_booking, gcash_reference_number='1234-5678-90123')
        self.assertEqual(Payment.objects.count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.create(booking=other_booking, amount=1200, payment_method='gcash',
                transaction_ref='race', gcash_reference_key='1234567890123')

    def test_legacy_reference_cannot_be_reused(self):
        Payment.objects.create(booking=self.booking, amount=100, payment_method='gcash',
            payment_status='verified', transaction_ref='legacy-ref', gcash_reference_number='1234-5678-90123')
        self.submit(payment_option='balance', amount='5900')
        self.assertEqual(Payment.objects.count(), 1)

    def test_pending_proof_blocks_second_submission(self):
        self.submit()
        self.submit(gcash_reference_number='9876543210123')
        self.assertEqual(Payment.objects.count(), 1)

    def test_full_and_balance_use_saved_booking_price(self):
        self.submit(payment_option='full', amount='6000')
        self.assertEqual(Payment.objects.get().amount, 6000)
        Payment.objects.all().delete()
        Payment.objects.create(booking=self.booking, amount=1200, payment_method='gcash',
            payment_type='downpayment', payment_status='verified', transaction_ref='deposit')
        self.submit(amount='4800', payment_option='balance')
        self.assertEqual(Payment.objects.get(payment_status='pending').payment_type, 'balance')

    def test_proof_requires_owner_or_admin_and_has_no_public_url_in_admin_html(self):
        self.submit()
        payment = Payment.objects.get()
        url = reverse('payment_proof', args=[payment.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertTrue(b''.join(response.streaming_content))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_payment_detail', args=[payment.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, url)
        self.assertNotContains(response, '/media/'+payment.receipt_image.name)

    def test_admin_must_confirm_merchant_check_before_crediting_new_proof(self):
        self.submit()
        payment = Payment.objects.get()
        self.client.force_login(self.admin)
        url = reverse('admin_payment_action', args=[payment.pk, 'verify'])
        self.client.post(url)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'pending')
        self.client.post(url, {'merchant_confirmed':'on'})
        payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(payment.payment_status, 'verified')
        self.assertEqual(self.booking.status, 'confirmed')
        notices = Notification.objects.count()
        self.client.post(url, {'merchant_confirmed':'on'})
        self.assertEqual(Notification.objects.count(), notices)

    def test_rejection_releases_reference_for_corrected_proof(self):
        self.submit()
        payment = Payment.objects.get()
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_payment_action', args=[payment.pk, 'reject']), {'admin_notes':'Unreadable proof'})
        payment.refresh_from_db()
        self.assertIsNone(payment.gcash_reference_key)
        self.client.force_login(self.user)
        self.submit()
        self.assertEqual(Payment.objects.filter(payment_status='pending').count(), 1)

    def test_expired_booking_cannot_accept_new_proof(self):
        self.booking.payment_due_at = timezone.now()-timedelta(minutes=1)
        self.booking.save()
        self.submit()
        self.assertFalse(Payment.objects.exists())

    @patch('app.views.payments.create_paymongo_checkout_session')
    def test_legacy_checkout_creation_route_cannot_charge(self, checkout):
        self.client.post(reverse('create_paymongo_checkout', args=[self.booking.pk]),
            {'amount':'6000', 'payment_option':'full', 'refund_ack':'on'})
        checkout.assert_not_called()
        self.assertFalse(Payment.objects.exists())

    def test_unfinished_provider_transaction_requires_review_before_qr_payment(self):
        Payment.objects.create(booking=self.booking, amount=1200, payment_method='paymongo_gcash',
            transaction_ref='old-open', paymongo_checkout_session_id='cs_open',
            paymongo_checkout_url='https://checkout.paymongo.com/open')
        response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertContains(response, 'previous checkout')
        self.assertNotContains(response, 'name="receipt_image"')
        self.assertNotContains(response, 'href="https://checkout.paymongo.com/open"')
        self.submit()
        self.assertEqual(Payment.objects.count(), 1)

    def test_settings_save_qr_details_and_validate_uploads(self):
        self.client.force_login(self.admin)
        url = reverse('admin_gcash_config')
        result = self.client.post(url, {'downpayment_percent':'30', 'gcash_name':'New Merchant',
            'gcash_number':'', 'instructions':'Check recipient before paying.', 'qr_code_image':png('new-qr.png')},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(result.status_code, 200)
        self.config.refresh_from_db()
        self.assertEqual(self.config.gcash_name, 'New Merchant')
        self.assertIn('new-qr', self.config.qr_code_image.name)
        result = self.client.post(url, {'downpayment_percent':'30', 'gcash_name':'New Merchant',
            'qr_code_image':SimpleUploadedFile('bad.png', b'bad', content_type='image/png')},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(result.status_code, 400)

    def test_payment_submission_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('submit_payment', args=[self.booking.pk]), self.payload()).status_code, 403)

    def test_recipient_signature_prevents_tampering_and_preserves_displayed_recipient(self):
        data = self.payload(recipient_token='forged')
        self.client.post(reverse('submit_payment', args=[self.booking.pk]), data)
        self.assertFalse(Payment.objects.exists())
        data = self.payload()
        self.config.gcash_name = 'Replacement account'
        self.config.save()
        self.client.post(reverse('submit_payment', args=[self.booking.pk]), data)
        self.assertEqual(Payment.objects.get().gcash_recipient_name, 'Balloorina Merchant')

    def test_hundred_percent_downpayment_is_recorded_as_full_payment(self):
        self.config.downpayment_percent = 100
        self.config.save()
        self.submit(amount='6000')
        self.assertEqual(Payment.objects.get().payment_type, 'full')

    def test_oversized_proof_cannot_create_payment(self):
        self.submit(receipt_image=SimpleUploadedFile('large.png', png().read()+b'x'*(5*1024*1024), content_type='image/png'))
        self.assertFalse(Payment.objects.exists())

    @patch('app.views.payments.retrieve_paymongo_checkout_session')
    def test_provider_confirmed_expiry_allows_qr_without_deleting_history(self, retrieve):
        legacy = Payment.objects.create(booking=self.booking, amount=1200, payment_method='paymongo_gcash',
            transaction_ref='expired-at-provider', paymongo_checkout_session_id='cs_expired')
        retrieve.return_value = {'data':{'attributes':{'status':'expired'}}}
        self.client.get(reverse('paymongo_success', args=[self.booking.pk]))
        self.submit()
        self.assertEqual(Payment.objects.count(), 2)
        legacy.refresh_from_db()
        self.assertIn('Provider confirmed terminal:', legacy.notes)

    def test_payment_guidance_uses_qr_readiness_and_manual_verification(self):
        from .ai_support_knowledge import focused_support_facts
        facts = focused_support_facts('How do I pay with GCash?', ['payment_help'])
        self.assertIn('GCash QR', str(facts))
        self.assertIn('proof', str(facts))
        self.assertNotIn('GCash through online checkout', str(facts))

    @patch('app.payment_storage.PaymentProofStorage._save', side_effect=OSError('storage unavailable'))
    def test_storage_outage_does_not_create_or_credit_payment(self, save):
        response = self.submit()
        self.assertLess(response.status_code, 500)
        self.assertFalse(Payment.objects.exists())
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'pending_payment')

    def test_qr_download_is_an_attachment_with_exact_configured_image(self):
        response = self.client.get(reverse('gcash_qr_download'), {'recipient':self.payload()['recipient_token']})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(b''.join(response.streaming_content))

    def test_payment_tracking_exposes_gcash_reference_and_private_proof_link(self):
        self.submit()
        payment = Payment.objects.get()
        response = self.client.get(reverse('my_payments'))
        self.assertContains(response, 'GCash reference')
        self.assertContains(response, 'data-pay-gcash-reference="1234567890123"')
        self.assertContains(response, reverse('payment_proof', args=[payment.pk]))

    @patch('app.views.payments.retrieve_paymongo_checkout_session')
    def test_rejected_received_legacy_return_does_not_reopen_payment(self, retrieve):
        payment = Payment.objects.create(booking=self.booking, amount=1200, payment_method='paymongo_gcash',
            transaction_ref='already-reviewed', payment_status='rejected', paymongo_checkout_session_id='cs_reviewed',
            paymongo_payment_id='pay_reviewed', received_at=timezone.now(), notes='Reviewed and rejected by admin')
        retrieve.return_value = {'data':{'attributes':{'status':'paid'}}}
        self.client.get(reverse('paymongo_success', args=[self.booking.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'rejected')
        retrieve.assert_not_called()

    def test_redisplayed_invalid_proof_keeps_signed_recipient_and_qr_together(self):
        data = self.payload(gcash_sender_name='')
        old_qr_url = self.config.qr_code_image.url
        self.config.gcash_name = 'Replacement Merchant'
        self.config.qr_code_image = png('replacement.png')
        self.config.save()
        response = self.client.post(reverse('submit_payment', args=[self.booking.pk]), data)
        self.assertContains(response, 'Balloorina Merchant')
        self.assertContains(response, old_qr_url)
        self.assertNotContains(response, 'Replacement Merchant')

    def test_account_media_purge_deletes_detached_private_payment_proof(self):
        from .account_deletion import queue_account_media, purge_account_media
        self.submit()
        payment = Payment.objects.get()
        storage, name = payment.receipt_image.storage, payment.receipt_image.name
        self.assertTrue(storage.exists(name))
        Payment.objects.filter(pk=payment.pk).update(receipt_image='')
        queue_account_media([name])
        purge_account_media()
        self.assertFalse(storage.exists(name))

    def test_catalog_payment_knowledge_does_not_enable_legacy_provider_checkout(self):
        from .services import _build_catalog_chunks
        chunks = str(_build_catalog_chunks())
        self.assertIn('GCash QR', chunks)
        self.assertNotIn('GCash via PayMongo checkout', chunks)
        self.assertNotIn('until PAYMONGO_SECRET_KEY is set', chunks)

    @patch('app.views.payments.retrieve_paymongo_checkout_session')
    def test_status_check_targets_blocking_older_checkout(self, retrieve):
        blocking = Payment.objects.create(booking=self.booking, amount=1200, payment_method='paymongo_gcash',
            transaction_ref='old-blocker', paymongo_checkout_session_id='cs_old', notes='Customer cancelled checkout')
        Payment.objects.create(booking=self.booking, amount=1200, payment_method='paymongo_gcash',
            transaction_ref='new-terminal', paymongo_checkout_session_id='cs_new',
            notes='PayMongo checkout expired. Provider confirmed terminal: expired.')
        retrieve.return_value = {'data':{'attributes':{'status':'expired'}}}
        response = self.client.get(reverse('payment_page', args=[self.booking.pk]))
        self.assertContains(response, f'payment_id={blocking.pk}')
        self.client.get(reverse('paymongo_success', args=[self.booking.pk]), {'payment_id':blocking.pk})
        retrieve.assert_called_once_with('cs_old')

    def test_legacy_reference_with_non_ascii_whitespace_cannot_be_reused(self):
        Payment.objects.create(booking=self.booking, amount=100, payment_method='gcash',
            payment_status='verified', transaction_ref='legacy-spaces', gcash_reference_number='1234\t5678\u00a090123')
        self.submit(payment_option='balance', amount='5900')
        self.assertEqual(Payment.objects.count(), 1)


class AuthenticatedProofStorageTests(SimpleTestCase):
    @override_settings(PAYMENT_PROOF_USE_CLOUDINARY=True, CLOUDINARY_STORAGE={
        'CLOUD_NAME':'proof-test', 'API_KEY':'test-key', 'API_SECRET':'test-secret'})
    @patch('cloudinary.uploader.upload')
    @patch('requests.get')
    def test_cloudinary_upload_and_read_use_authenticated_delivery(self, get, upload):
        from .payment_storage import PaymentProofStorage
        upload.return_value = {'public_id':'private_payment_receipts/example', 'format':'png'}
        storage = PaymentProofStorage()
        name = storage.save('proof.png', png())
        self.assertEqual(upload.call_args.kwargs['type'], 'authenticated')
        self.assertEqual(name, 'private/cloudinary/private_payment_receipts/example.png')
        get.return_value.content = png().read()
        storage.open(name).close()
        self.assertIn('/image/authenticated/', get.call_args.args[0])
        self.assertIn('/s--', get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs['timeout'], 20)
        with self.assertRaises(ValueError):
            storage.url(name)
