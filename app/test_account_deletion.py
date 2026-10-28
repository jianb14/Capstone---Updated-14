import io
import re
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import authenticate
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, Client, RequestFactory
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from . import email_otp
from .account_deletion import deletion_blockers, purge_account_media
from .request_protection import bucket_key
from .models import (User, Booking, Payment, BookingChangeRequest, Review, ReviewImage,
    UserDesign, EmailOTPChallenge, AccountMediaRemoval, ConcernTicket, ConcernImage, AuditLog,
    RequestRateBucket, ChatSession, ChatMessage, ChatNotification, AiRequest, AiGeneratedImage, BookingStatusLog)


def picture(name='account.png'):
    buffer=io.BytesIO(); Image.new('RGB',(8,8),'gold').save(buffer,format='PNG')
    return SimpleUploadedFile(name,buffer.getvalue(),content_type='image/png')


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(username='delete-owner',email='delete@example.com',
            password='CurrentPassword!25',first_name='Jamie',last_name='Rivera',phone_number='09170000000',
            role='customer',email_verified=True)
        self.client.force_login(self.user)
        self.url=reverse('delete_my_account')

    def post(self,action,**data):
        return self.client.post(self.url,{'action':action,**data},HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def code(self):
        response=self.post('request_code',password='CurrentPassword!25')
        self.assertEqual(response.status_code,200,response.content)
        return re.search(r'\b\d{6}\b',mail.outbox[-1].body)[0]

    def grant(self):
        response=self.post('verify',code=self.code())
        self.assertEqual(response.status_code,200,response.content)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)

    def booking(self,status='completed',total=100):
        return Booking.objects.create(user=self.user,event_date=date(2026,1,1),event_type='Birthday',
            event_location='Private home address',status=status,total_price=total)

    def pay(self,booking,status='verified',**kwargs):
        return Payment.objects.create(booking=booking,amount=booking.total_price,payment_status=status,
            payment_method='gcash',transaction_ref=f'proof-{Payment.objects.count()}',**kwargs)

    def test_auth_roles_post_only_csrf_and_owner_identity(self):
        self.assertEqual(self.client.get(self.url).status_code,405)
        secure=Client(enforce_csrf_checks=True); secure.force_login(self.user)
        self.assertEqual(secure.post(self.url,{'action':'confirm'}).status_code,403)
        self.client.logout(); self.assertEqual(self.post('confirm').status_code,403)
        admin=User.objects.create_user(username='deletion-admin',role='admin',email_verified=True)
        self.client.force_login(admin); self.assertEqual(self.post('request_code',password='x').status_code,403)
        self.client.force_login(self.user)
        self.post('request_code',password='CurrentPassword!25',user_id=admin.pk)
        self.assertEqual(mail.outbox[-1].to,[self.user.email])
        self.assertFalse(EmailOTPChallenge.objects.filter(user=admin).exists())

    def test_all_active_booking_statuses_block_even_when_fully_paid(self):
        for state in ('pending','pending_payment','confirmed','cancel_requested'):
            booking=self.booking(state); self.pay(booking)
            self.assertTrue(deletion_blockers(self.user),state)
            self.assertEqual(self.post('request_code',password='CurrentPassword!25').status_code,409)
            booking.delete()
        self.assertEqual(len(mail.outbox),0)

    def test_completed_balance_uses_verified_applied_payments(self):
        booking=self.booking(); booking.payment_status='paid'; booking.save()
        self.assertTrue(deletion_blockers(self.user))
        pay=self.pay(booking); pay.amount=Decimal('25'); pay.save()
        self.assertIn('75.00',str(deletion_blockers(self.user)))
        pay.amount=booking.total_price; pay.applied_to_booking=False; pay.save()
        self.assertTrue(deletion_blockers(self.user))
        pay.applied_to_booking=True; pay.save(); self.assertEqual(deletion_blockers(self.user),[])

    def test_terminal_quotes_pending_proofs_open_checkout_and_active_changes(self):
        cancelled=self.booking('cancelled'); expired=self.booking('expired')
        self.assertEqual(deletion_blockers(self.user),[])
        payment=self.pay(cancelled,'pending')
        self.assertTrue(deletion_blockers(self.user))
        payment.payment_method='paymongo_card'; payment.notes='Checkout expired'; payment.save()
        self.assertEqual(deletion_blockers(self.user),[])
        payment.paymongo_payment_id='paid-provider-id'; payment.save()
        self.assertTrue(deletion_blockers(self.user))
        payment.payment_status='rejected'; payment.save()
        change=BookingChangeRequest.objects.create(booking=expired,reason='Change',original_total=100,quoted_total=100)
        self.assertTrue(deletion_blockers(self.user))
        change.status='withdrawn'; change.save(); self.assertEqual(deletion_blockers(self.user),[])

    def test_password_required_email_failure_and_cooldown_preserve_account(self):
        self.assertEqual(self.post('request_code',password='wrong').status_code,400)
        self.assertEqual(len(mail.outbox),0)
        with patch('app.email_otp.send_mail',side_effect=RuntimeError('Email offline')):
            self.assertEqual(self.post('request_code',password='CurrentPassword!25').status_code,503)
        self.user.refresh_from_db(); self.assertIsNone(self.user.deleted_at)
        self.assertFalse(EmailOTPChallenge.objects.filter(user=self.user,consumed_at__isnull=True).exists())
        self.assertEqual(self.post('request_code',password='CurrentPassword!25').status_code,429)

    def test_code_is_session_password_email_and_purpose_bound(self):
        code=self.code()
        other=Client(); other.force_login(self.user)
        self.assertEqual(other.post(self.url,{'action':'verify','code':code}).status_code,400)
        challenge=EmailOTPChallenge.objects.get(user=self.user,purpose='delete')
        self.assertNotEqual(challenge.code_digest,code)
        self.assertEqual(self.post('verify',code='000000' if code!='000000' else '111111').status_code,400)
        self.user.email='changed@example.com'; self.user.save(update_fields=['email'])
        self.assertEqual(self.post('verify',code=code).status_code,400)
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,400)

    def test_no_deletion_on_verification_cancel_expiry_and_final_recheck(self):
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,400)
        self.grant()
        self.assertEqual(self.post('confirm').status_code,400)
        booking=self.booking('confirmed')
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,409)
        self.user.refresh_from_db(); self.assertIsNone(self.user.deleted_at)
        booking.status='cancelled'; booking.save()
        EmailOTPChallenge.objects.filter(user=self.user,purpose='delete').update(grant_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,400)
        self.assertEqual(self.post('cancel').status_code,200)
        self.assertFalse(EmailOTPChallenge.objects.filter(user=self.user,consumed_at__isnull=True).exists())

    def test_permanent_removal_keeps_financial_rows_revokes_sessions_and_removes_files(self):
        booking=self.booking(); pay=self.pay(booking,receipt_image=picture('receipt.png'),gcash_sender_name='Jamie',paymongo_contact_number='09170000000')
        review=Review.objects.create(user=self.user,booking=booking,rating=5,comment='Personal review')
        image=ReviewImage.objects.create(review=review,image=picture('review.png'))
        design=UserDesign.objects.create(user=self.user,name='Personal design',canvas_json='{}',thumbnail=picture('design.png'))
        paths=[field.name for field in (pay.receipt_image,image.image,design.thumbnail)]
        storage=image.image.storage
        second=Client(); second.force_login(self.user)
        self.grant()
        with self.captureOnCommitCallbacks(execute=True):
            response=self.post('confirm',acknowledge='yes')
        self.assertEqual(response.status_code,200,response.content)
        self.user.refresh_from_db(); pay.refresh_from_db(); booking.refresh_from_db()
        self.assertIsNotNone(self.user.deleted_at)
        self.assertFalse(self.user.is_active); self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.user.email,''); self.assertIsNone(self.user.phone_number)
        self.assertEqual(self.user.get_full_name(),'Deleted customer')
        self.assertEqual(Booking.objects.filter(pk=booking.pk).count(),1)
        self.assertEqual(pay.amount,100); self.assertEqual(pay.payment_status,'verified')
        self.assertEqual(booking.event_location,'Removed after account deletion')
        self.assertEqual(pay.gcash_sender_name,''); self.assertEqual(pay.receipt_image.name,'')
        self.assertFalse(Review.objects.filter(user=self.user).exists()); self.assertFalse(UserDesign.objects.filter(user=self.user).exists())
        for name in paths: self.assertFalse(storage.exists(name),name)
        self.assertFalse(AccountMediaRemoval.objects.exists())
        self.assertNotIn('_auth_user_id',self.client.session)
        self.assertEqual(second.get(reverse('my_profile')).status_code,302)
        self.assertIsNone(authenticate(username=self.user.username,password='CurrentPassword!25'))
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,403)

    def test_storage_failure_is_durable_and_shared_files_are_protected(self):
        design=UserDesign.objects.create(user=self.user,canvas_json='{}',thumbnail=picture('retry.png'))
        name=design.thumbnail.name
        self.grant()
        with patch('app.account_deletion.default_storage.delete',side_effect=OSError('Storage offline')):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.post('confirm',acknowledge='yes').status_code,200)
        self.assertEqual(AccountMediaRemoval.objects.get().attempts,1)
        self.assertTrue(design.thumbnail.storage.exists(name))
        self.assertEqual(purge_account_media(),1)
        self.assertFalse(design.thumbnail.storage.exists(name))

    def test_deleted_transaction_owner_cannot_be_reactivated_edited_reset_or_hard_deleted(self):
        self.grant(); self.post('confirm',acknowledge='yes')
        admin=User.objects.create_user(username='retention-admin',role='admin',password='Password!25')
        self.client.force_login(admin)
        for route in ('admin_user_edit','admin_user_toggle','admin_user_reset_password','admin_user_delete'):
            response=self.client.post(reverse(route,args=[self.user.pk]))
            self.assertEqual(response.status_code,404,(route,response.content))
        self.assertEqual(self.client.get(reverse('admin_user_detail',args=[self.user.pk])).status_code,200)
        self.assertNotContains(self.client.get(reverse('admin_user_list')),self.user.username)

    def test_failed_resend_preserves_old_code_and_successful_resend_replaces_it(self):
        code=self.code()
        original=self.client.session[email_otp.session_key('delete')].copy()
        RequestRateBucket.objects.all().delete()
        with patch('app.email_otp.send_mail',side_effect=RuntimeError('offline')):
            self.assertEqual(self.post('resend').status_code,503)
        self.assertEqual(self.client.session[email_otp.session_key('delete')],original)
        self.assertTrue(email_otp.bound(email_otp.get_challenge(original,'delete'),self.user,original))
        RequestRateBucket.objects.all().delete()
        self.assertEqual(self.post('resend').status_code,200)
        replacement=re.search(r'\b\d{6}\b',mail.outbox[-1].body)[0]
        self.assertNotEqual(code,replacement)
        self.assertEqual(self.post('verify',code=code).status_code,400)
        self.assertEqual(self.post('verify',code=replacement).status_code,200)
        self.assertEqual(self.post('verify',code=replacement).status_code,400)

    def test_wrong_guess_budget_survives_resend_and_code_expiry_is_enforced(self):
        code=self.code()
        for _ in range(5):
            response=self.post('verify',code='000000' if code!='000000' else '111111')
        self.assertEqual(response.status_code,429)
        self.assertGreater(response.json()['retry_after'],0)
        self.assertEqual(self.post('verify',code=code).status_code,429)
        RequestRateBucket.objects.filter(key__in=[
            bucket_key('account-deletion-otp:cooldown','127.0.0.1'),
            bucket_key('account-deletion-otp:email-cooldown',self.user.email)]).delete()
        self.assertEqual(self.post('resend').status_code,200)
        replacement=re.search(r'\b\d{6}\b',mail.outbox[-1].body)[0]
        self.assertEqual(self.post('verify',code=replacement).status_code,429)
        RequestRateBucket.objects.all().delete()
        EmailOTPChallenge.objects.filter(user=self.user,consumed_at__isnull=True).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post('verify',code=replacement).status_code,400)

    def test_password_change_and_wrong_purpose_cannot_authorize_deletion(self):
        self.grant()
        context=self.client.session[email_otp.session_key('delete')].copy()
        self.user.set_password('ChangedPassword!25'); self.user.save(update_fields=['password'])
        self.client.force_login(self.user)
        session=self.client.session; session[email_otp.session_key('delete')]=context; session.save()
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,400)
        EmailOTPChallenge.objects.filter(pk=context['id']).update(purpose='reset',password_digest=email_otp.digest('password',self.user.password))
        self.assertEqual(self.post('confirm',acknowledge='yes').status_code,400)
        self.user.refresh_from_db(); self.assertIsNone(self.user.deleted_at)

    def test_shared_storage_file_is_not_removed_from_another_owner(self):
        design=UserDesign.objects.create(user=self.user,canvas_json='{}',thumbnail=picture('shared.png'))
        other=User.objects.create_user(username='shared-owner',role='customer')
        retained=UserDesign.objects.create(user=other,canvas_json='{}',thumbnail=design.thumbnail.name)
        self.grant()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post('confirm',acknowledge='yes').status_code,200)
        retained.refresh_from_db()
        self.assertTrue(retained.thumbnail.storage.exists(retained.thumbnail.name))
        self.assertFalse(AccountMediaRemoval.objects.exists())

    def test_ai_chat_concerns_and_status_notes_are_removed(self):
        booking=self.booking(total=0)
        log=BookingStatusLog.objects.create(booking=booking,new_status='completed',notes='Private address')
        admin=User.objects.create_user(username='chat-operator',role='admin')
        session=ChatSession.objects.create(user=self.user)
        message=ChatMessage.objects.create(session=session,sender=self.user,receiver=admin,message='private',image=picture('chat.png'))
        ChatNotification.objects.create(user=self.user,message='private')
        request=AiRequest.objects.create(user=self.user,session=session,user_message=message,fingerprint='f',input_text='private')
        image=AiGeneratedImage.objects.create(request=request,image=picture('ai.png'),prompt='private')
        concern=ConcernTicket.objects.create(user=self.user,subject='Private',message='private')
        concern_image=ConcernImage.objects.create(concern=concern,image=picture('concern.png'))
        files=[(obj.image.storage,obj.image.name) for obj in (message,image,concern_image)]
        self.grant()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post('confirm',acknowledge='yes').status_code,200)
        for model in (AiRequest,ChatSession,ChatNotification,ConcernTicket):
            self.assertFalse(model.objects.filter(user=self.user).exists())
        self.assertFalse(ChatMessage.objects.filter(pk=message.pk).exists())
        log.refresh_from_db(); self.assertEqual(log.notes,'')
        for storage,name in files: self.assertFalse(storage.exists(name))

    def test_failed_deletion_rolls_back_data_and_does_not_delete_files(self):
        design=UserDesign.objects.create(user=self.user,canvas_json='{}',thumbnail=picture('rollback.png'))
        from .account_deletion import remove_account
        def fail_after_removal(user):
            remove_account(user)
            raise RuntimeError('Unexpected database operation failed')
        self.grant(); self.client.raise_request_exception=False
        with patch('app.views.account.remove_account',side_effect=fail_after_removal):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.post('confirm',acknowledge='yes').status_code,500)
        self.user.refresh_from_db(); self.assertIsNone(self.user.deleted_at)
        self.assertTrue(UserDesign.objects.filter(pk=design.pk).exists())
        self.assertTrue(design.thumbnail.storage.exists(design.thumbnail.name))
        self.assertFalse(AccountMediaRemoval.objects.exists())
        self.assertIn('_auth_user_id',self.client.session)

    def test_lifecycle_middleware_rolls_back_converted_server_errors(self):
        from .account_lifecycle import CustomerAccountLifecycleMiddleware
        request=RequestFactory().post('/test/'); request.user=self.user
        def failing_response(request):
            UserDesign.objects.create(user=request.user,canvas_json='{}')
            return HttpResponse(status=500)
        response=CustomerAccountLifecycleMiddleware(failing_response)(request)
        self.assertEqual(response.status_code,500)
        self.assertFalse(UserDesign.objects.filter(user=self.user).exists())

    def test_late_ai_result_cannot_recreate_removed_content_and_its_file_is_purged(self):
        import uuid
        from django.core.files.storage import default_storage
        from .ai_jobs import complete_request
        job=AiRequest.objects.create(user=self.user,fingerprint='late',input_text='private',state='running',lease_token=uuid.uuid4())
        job_id,token=job.pk,job.lease_token
        self.grant(); self.post('confirm',acknowledge='yes')
        name=default_storage.save('ai_generated/late.png',picture())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(complete_request(job_id,token,{'text':'late result'},assets=[{'name':name,'prompt':'private','seed':0}]))
        self.assertFalse(default_storage.exists(name))
        self.assertFalse(AiRequest.objects.filter(pk=job_id).exists())
        self.assertFalse(ChatMessage.objects.filter(receiver=self.user).exists())
