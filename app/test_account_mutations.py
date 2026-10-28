"""JSON contracts for account forms, including session-bound password verification."""
import re
from datetime import timedelta

from django.core import mail
from django.test import Client,TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking,EmailOTPChallenge,Package,ServiceChargeConfig,User
from . import test_booking_changes as change_fixtures


class AccountMutationTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(username='async-account',email='async@example.com',role='customer',
            first_name='Jamie',last_name='Rivera',phone_number='09170000000',email_verified=True,password='ExistingPassword!25')
        self.client.force_login(self.user)
        self.day=timezone.localdate()+timedelta(days=45)
        self.booking=Booking.objects.create(user=self.user,event_type='Birthday',event_date=self.day,
            event_location='Test venue in Cavite',status='pending',total_price=6000,package_type='Package A')
        Package.objects.create(name='Package A',price=5000)
        ServiceChargeConfig.objects.create(pk=1,amount=1000)

    def post(self,route,data,**kwargs):
        return self.client.post(route,data,HTTP_X_REQUESTED_WITH='XMLHttpRequest',**kwargs)

    def test_profile_save_and_field_errors_are_json_without_redirects(self):
        url=reverse('update_my_profile')
        response=self.post(url,{'first_name':'Alex','last_name':'','phone_number':'09170000000'})
        self.assertEqual(response.status_code,400)
        self.assertIn('last_name',response.json()['errors'])
        self.user.refresh_from_db();self.assertEqual(self.user.first_name,'Jamie')
        response=self.post(url,{'first_name':'Alex','last_name':'Rivera','phone_number':'09170000000'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['redirect_url'],reverse('my_profile'))

    def test_pending_booking_edit_returns_validation_errors_and_then_saves(self):
        url=reverse('edit_booking',args=[self.booking.pk])
        data={'event_type':'Birthday','event_date':self.day.isoformat(),'start_time':'07:00','end_time':'10:00',
            'event_location':'Test venue in Cavite','package_type':'Package A','total_price':'6000'}
        for field,value in [('event_date','bad'),('start_time','bad'),('total_price','NaN'),('event_type','x'*51),('event_location','x'*256)]:
            response=self.post(url,{**data,field:value})
            self.assertEqual(response.status_code,400,(field,response.content))
            self.assertFalse(response.json()['success'])
        response=self.post(url,{**data,'event_type':'Updated birthday'})
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(response.json()['success'])
        self.booking.refresh_from_db();self.assertEqual(self.booking.event_type,'Updated birthday')

    def test_delete_preserves_ownership_status_and_csrf_restrictions(self):
        url=reverse('delete_booking',args=[self.booking.pk])
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post(url,HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,403)
        other=User.objects.create_user(username='async-stranger',role='customer')
        self.client.force_login(other);self.assertEqual(self.post(url,{}).status_code,403)
        self.client.force_login(self.user)
        self.booking.status='confirmed';self.booking.save()
        self.assertEqual(self.post(url,{}).status_code,409)
        self.booking.status='pending';self.booking.save()
        self.assertTrue(self.post(url,{}).json()['success'])
        self.assertFalse(Booking.objects.filter(pk=self.booking.pk).exists())

    def start_password(self):
        response=self.post(reverse('change_password'),{'old_password':'ExistingPassword!25',
            'new_password1':'NewPassword!26','new_password2':'NewPassword!26'})
        self.assertTrue(response.json()['success'],response.content)
        return re.search(r'(?m)^\d{6}$',mail.outbox[-1].body).group()

    def test_inline_password_otp_keeps_session_and_changes_only_after_verification(self):
        url=reverse('verify_change_password_otp')
        self.assertEqual(self.client.get(url,HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,400)
        code=self.start_password()
        response=self.client.get(url,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['masked_email'],'a***@example.com')
        self.user.refresh_from_db();self.assertTrue(self.user.check_password('ExistingPassword!25'))
        wrong='000000' if code!='000000' else '111111'
        self.assertEqual(self.post(url,{'code':wrong}).status_code,400)
        self.assertEqual(self.post(url,{'action':'resend'}).status_code,429)
        response=self.post(url,{'code':code})
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(response.json()['verified'])
        self.user.refresh_from_db();self.assertTrue(self.user.check_password('NewPassword!26'))
        self.assertEqual(self.client.get(reverse('my_profile')).status_code,200)
        self.assertEqual(self.post(url,{'code':code}).status_code,400)

    def test_inline_password_otp_cannot_cross_sessions_or_verify_an_expired_code(self):
        code=self.start_password();url=reverse('verify_change_password_otp')
        other=Client();other.force_login(self.user)
        self.assertEqual(other.post(url,{'code':code},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,400)
        EmailOTPChallenge.objects.filter(user=self.user,purpose='change').update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post(url,{'code':code}).status_code,400)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password('ExistingPassword!25'))


class AccountChangeActionTests(TestCase):
    setUp=change_fixtures.BookingChangeTests.setUp
    data=change_fixtures.BookingChangeTests.data
    submit=change_fixtures.BookingChangeTests.submit
    quote=change_fixtures.BookingChangeTests.quote

    def test_quote_acceptance_and_withdrawal_return_json_and_keep_validation(self):
        change=self.submit(motto_text='A new celebration')
        self.quote(change);self.client.force_login(self.user)
        url=reverse('customer_booking_change_action',args=[self.booking.pk,change.pk,'accept'])
        self.assertEqual(self.client.post(url,{},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,400)
        response=self.client.post(url,{'accept_quote':'on'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        change.refresh_from_db();self.assertEqual(change.status,'applied')
        change=self.submit(motto_text='Another celebration',change_reason='A separate new change request')
        url=reverse('customer_booking_change_action',args=[self.booking.pk,change.pk,'withdraw'])
        response=self.client.post(url,{},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        change.refresh_from_db();self.assertEqual(change.status,'withdrawn')
