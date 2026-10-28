"""Exercise settings through their admin save and the customer-facing consumers."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Booking, Package, SiteSettings, User, UserDesign


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SiteSettingsIntegrationTests(TestCase):
    def setUp(self):
        from .test_site_settings_save import UnifiedSiteSettingsTests
        UnifiedSiteSettingsTests.setUp(self)
        self.customer = User.objects.create_user(username='settings-integration-customer', email='customer@example.com',
            role='customer', email_verified=True, first_name='Jamie', last_name='Rivera', phone_number='09171234567')
        self.customer_client = Client(); self.customer_client.force_login(self.customer)
        Package.objects.create(name='Package A', price=5000, features='Setup')
        self.data.update(site_name='Configured Studio', contact_email='hello@configured.example', contact_phone='+63 917 123 4567',
            address='Configured shop in Cavite', facebook_link='https://www.facebook.com/configured-studio',
            instagram_link='https://www.instagram.com/configured-studio/', booking_lead_time_days='7',
            booking_payment_window_hours='36', booking_design_lead_hours='48', booking_change_cutoff_hours='72',
            booking_min_duration_hours='3', booking_included_hours='4', booking_max_duration_hours='8',
            booking_overtime_rate='700.00', admin_emails_for_notifications='one@example.com, two@example.com')

    def save(self, **changes):
        response = self.client.post(reverse('admin_site_settings'), {**self.data, **changes}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(response.json()['success'])
        return response

    def payload(self, **changes):
        from .test_booking_design_step import _base_payload
        return _base_payload(event_date=(timezone.localdate()+timedelta(days=35)).isoformat(),
                             start_time='09:00', end_time='14:30', event_lat='14.414', event_lng='120.982', **changes)

    def test_every_setting_is_persisted_and_restored_on_next_get(self):
        self.save()
        site = SiteSettings.load(); self.config.refresh_from_db()
        from .site_settings_form import SiteSettingsForm
        from .logistics_settings import LogisticsSettingsForm
        for name in SiteSettingsForm.Meta.fields:
            with self.subTest(field=name):
                expected = True if name == 'email_notifications_enabled' else self.data[name]
                self.assertEqual(str(getattr(site,name)),str(expected))
        for name in LogisticsSettingsForm.Meta.fields:
            with self.subTest(field=name):
                actual = getattr(self.config,name)
                self.assertEqual(actual, self.data[name] if name == 'notes' else Decimal(self.data[name]))
        response = self.client.get(reverse('admin_site_settings'))
        for form_name in ('site_form','design_settings_form','logistics_settings_form'):
            form = response.context[form_name]
            for name in form.fields:
                if name in ('shop_lat','shop_lng'): continue
                value = form[name].value()
                expected = True if name == 'email_notifications_enabled' else self.data.get(name)
                if expected is not None:
                    if isinstance(value,Decimal):
                        self.assertEqual(value,Decimal(str(expected)),name)
                    else:
                        self.assertEqual(str(value),str(expected),name)

    def test_public_footer_and_title_use_saved_identity_contacts_and_social_links(self):
        self.save()
        visitor = Client()
        for route in ('home','about','services','gallery','package'):
            with self.subTest(route=route):
                response = visitor.get(reverse(route))
                self.assertEqual(response.status_code,200)
                for name in ('site_name','contact_email','contact_phone','address','facebook_link','instagram_link'):
                    self.assertContains(response,self.data[name])
                self.assertNotContains(response,'one@example.com')
                self.assertNotContains(response,'two@example.com')
                self.assertNotContains(response,'https://www.facebook.com/share/1HL7azRN8Z/')

    def test_clearing_optional_public_details_hides_them_instead_of_showing_old_values(self):
        self.save()
        self.save(contact_email='',contact_phone='',address='',facebook_link='',instagram_link='',shop_lat='',shop_lng='')
        response=Client().get(reverse('home'))
        for name in ('contact_email','contact_phone','address','facebook_link','instagram_link'):
            self.assertNotContains(response,self.data[name])
        self.assertNotContains(response,'balloorina.ph@gmail.com')
        self.assertNotContains(response,'+63 967 233 6222')
        self.assertContains(response,'Configured Studio')

    def test_saved_lead_time_reaches_the_picker_and_is_enforced_by_create(self):
        from .views.common import get_booking_lead_time_policy
        self.save()
        days, first_day=get_booking_lead_time_policy()
        self.assertEqual(days,7); self.assertEqual(first_day,timezone.localdate()+timedelta(days=7))
        page=self.customer_client.get(reverse('booking_page'))
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['duration_policy']['min_hours'],3)
        data=self.payload(); data['event_date']=(timezone.localdate()+timedelta(days=6)).isoformat()
        response=self.customer_client.post(reverse('create_booking'),data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(response.json()['success'])
        self.assertIn('7 day',response.json().get('message','')+response.json().get('error',''))
        self.assertFalse(Booking.objects.filter(user=self.customer).exists())

    def test_saved_duration_and_overtime_set_new_quotes_and_preserve_existing_booking(self):
        from .views.common import get_booking_price_breakdown
        self.save()
        response=self.customer_client.post(reverse('create_booking'),self.payload(),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'],response.content)
        booking=Booking.objects.get(user=self.customer)
        self.assertEqual(booking.duration_minutes,330)
        self.assertEqual(booking.overtime_hours,2)
        self.assertEqual(booking.overtime_fee,Decimal('1400'))
        self.assertEqual(booking.logistics_fee,Decimal('1200'))
        self.assertEqual(booking.total_price,Decimal('7600'))
        self.assertEqual(booking.fee_policy_snapshot['included_hours'],4)
        self.save(booking_overtime_rate='999',amount='2500',notes='New logistics policy')
        booking.refresh_from_db()
        self.assertEqual(booking.total_price,Decimal('7600'))
        self.assertEqual(booking.overtime_fee,Decimal('1400'))
        self.assertEqual(booking.logistics_fee,Decimal('1200'))
        self.assertEqual(get_booking_price_breakdown(booking)['computed_total'],Decimal('7600'))

    def test_saved_minimum_and_maximum_duration_are_enforced_by_booking_create(self):
        self.save()
        for end in ('11:00','18:00'):
            data=self.payload();data['end_time']=end
            response=self.customer_client.post(reverse('create_booking'),data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertFalse(response.json()['success'],response.content)
        self.assertFalse(Booking.objects.filter(user=self.customer).exists())

    def test_saved_payment_and_design_deadlines_and_change_cutoff_are_used(self):
        from .booking_lifecycle import event_start_at,set_approval_deadlines
        from .booking_changes import eligibility
        self.save()
        now=timezone.now(); event=timezone.localtime(now)+timedelta(hours=50)
        booking=Booking.objects.create(user=self.customer,event_date=event.date(),event_time=event.time().replace(tzinfo=None),
            event_location='Venue',status='confirmed',total_price=5000)
        set_approval_deadlines(booking,now)
        self.assertEqual(booking.payment_due_at,now+timedelta(hours=36))
        self.assertEqual(booking.design_due_at,event_start_at(booking)-timedelta(hours=48))
        self.assertFalse(eligibility(booking,now)[0])
        self.save(booking_change_cutoff_hours='24')
        self.assertTrue(eligibility(booking,now)[0])
        # The payment window still stops at the event start for an earlier event.
        earlier=timezone.localtime(now)+timedelta(hours=10)
        booking.event_date=earlier.date();booking.event_time=earlier.time().replace(tzinfo=None)
        set_approval_deadlines(booking,now)
        self.assertEqual(booking.payment_due_at,event_start_at(booking))

    def test_saved_logistics_rates_free_distance_and_cap_are_used_by_quote(self):
        from .views.common import compute_logistics_quote
        self.save()
        with patch('app.views.common.haversine_km',return_value=45.1),patch('app.views.common.is_cavite_location',return_value=False):
            quote=compute_logistics_quote(14.6,120.98)
            self.assertEqual(quote['total'],Decimal('2240'))  # 1,200 + 26 additional km x 40
            self.assertTrue(quote['configured'])
        self.save(max_fee_cap='1500')
        with patch('app.views.common.haversine_km',return_value=45.1),patch('app.views.common.is_cavite_location',return_value=False):
            quote=compute_logistics_quote(14.6,120.98)
            self.assertEqual(quote['total'],Decimal('1500'));self.assertTrue(quote['capped'])
        with patch('app.views.common.is_cavite_location',return_value=True):
            self.assertEqual(compute_logistics_quote(14.414,120.982)['total'],Decimal('1200'))

    def test_saved_design_limit_reaches_customer_library_without_stale_cache(self):
        from .design_limits import saved_design_usage
        self.save(max_saved_designs='2')
        for i in range(2):UserDesign.objects.create(user=self.customer,name=f'Settings draft {i}',canvas_json='{"objects":[]}')
        self.assertTrue(saved_design_usage(self.customer)['at_limit'])
        self.save(max_saved_designs='3')
        usage=saved_design_usage(self.customer)
        self.assertEqual(usage['remaining'],1);self.assertFalse(usage['at_limit'])

    def test_saved_alert_toggle_and_recipients_control_actual_email_messages(self):
        from .views.common import send_admin_alert_email
        self.save()
        self.assertTrue(send_admin_alert_email('Configured alert','Test body'))
        self.assertEqual(mail.outbox[-1].to,['one@example.com','two@example.com'])
        disabled={**self.data};disabled.pop('email_notifications_enabled')
        response=self.client.post(reverse('admin_site_settings'),disabled,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'])
        self.assertFalse(send_admin_alert_email('Disabled alert','Not sent'))
        self.assertEqual(len(mail.outbox),1)
        self.save(admin_emails_for_notifications='')
        self.assertFalse(send_admin_alert_email('No recipients','Not sent'))
        self.assertEqual(len(mail.outbox),1)

    def test_invalid_fields_in_every_section_leave_the_saved_configuration_unchanged(self):
        self.save()
        from .models import ServiceChargeConfig
        original_site=SiteSettings.objects.values().get(pk=self.settings.pk)
        original_logistics=ServiceChargeConfig.objects.values().get(pk=1)
        for name,value in (
            ('site_name',''),('contact_email','invalid'),('facebook_link','javascript:alert(1)'),
            ('instagram_link','ftp://example.com'),('booking_lead_time_days','-1'),
            ('booking_payment_window_hours','0'),('booking_design_lead_hours','721'),
            ('booking_change_cutoff_hours','1.5'),('booking_min_duration_hours','0'),
            ('booking_included_hours','9'),('booking_max_duration_hours','169'),('booking_overtime_rate','NaN'),
            ('admin_emails_for_notifications','not-an-email'),('max_saved_designs','0'),
            ('amount','-1'),('free_radius_km','1001'),('per_km_rate','Infinity'),('max_fee_cap','-1'),('notes',''),
            ('shop_lat','91'),('shop_lng','-181'),('shop_lat',''),
        ):
            with self.subTest(field=name,value=value):
                response=self.client.post(reverse('admin_site_settings'),{**self.data,name:value},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(response.status_code,400,response.content)
                self.assertFalse(response.json()['success'])
                self.assertTrue(response.json()['errors'])
                self.assertEqual(SiteSettings.objects.values().get(pk=self.settings.pk),original_site)
                self.assertEqual(ServiceChargeConfig.objects.values().get(pk=1),original_logistics)

    def test_legacy_unsafe_social_urls_are_not_rendered_as_public_links(self):
        self.settings.facebook_link='javascript:alert(1)'
        self.settings.instagram_link='data:text/html,broken'
        self.settings.site_name='<script>business</script>'
        self.settings.save()
        response=Client().get(reverse('home'))
        self.assertNotContains(response,'href="javascript:')
        self.assertNotContains(response,'href="data:')
        self.assertNotContains(response,'<script>business</script>')
        self.assertContains(response,'&lt;script&gt;business&lt;/script&gt;')

    def test_public_details_update_on_the_next_request_without_leaking_private_configuration(self):
        self.save()
        visitor=Client()
        self.assertContains(visitor.get(reverse('home')),'hello@configured.example')
        self.save(contact_email='latest@configured.example')
        response=visitor.get(reverse('home'))
        self.assertContains(response,'latest@configured.example')
        self.assertNotContains(response,'hello@configured.example')
        self.assertNotContains(response,'one@example.com')

    def test_a_failed_logistics_write_rolls_back_business_design_and_audit_changes(self):
        from django.db import DatabaseError
        from .models import ServiceChargeConfig
        original_site=SiteSettings.objects.values().get(pk=self.settings.pk)
        original_config=ServiceChargeConfig.objects.values().get(pk=1)
        with patch.object(ServiceChargeConfig,'save',side_effect=DatabaseError('Simulated storage failure')):
            with self.assertRaises(DatabaseError):
                self.client.post(reverse('admin_site_settings'),self.data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(SiteSettings.objects.values().get(pk=self.settings.pk),original_site)
        self.assertEqual(ServiceChargeConfig.objects.values().get(pk=1),original_config)
        self.assertFalse(AuditLog.objects.filter(user=self.admin).exists())
