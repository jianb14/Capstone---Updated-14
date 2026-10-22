from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import ServiceChargeConfig, SiteSettings, User


class UnifiedSiteSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='all-settings-admin', role='admin')
        self.client.force_login(self.admin)
        self.settings = SiteSettings.load()
        self.config = ServiceChargeConfig.objects.create(pk=1, amount=1000, notes='Original notes.', shop_lat=14.4, shop_lng=120.9)
        self.data = {'settings_section': 'all', 'site_name': 'Updated business', 'contact_email': 'team@example.com',
            'contact_phone': '09000000000', 'address': 'Updated shop', 'facebook_link': '', 'instagram_link': '',
            'booking_lead_time_days': '3', 'booking_payment_window_hours': '24', 'booking_design_lead_hours': '24',
            'booking_change_cutoff_hours': '48', 'booking_min_duration_hours': '2', 'booking_included_hours': '3',
            'booking_max_duration_hours': '24', 'booking_overtime_rate': '550', 'email_notifications_enabled': 'on',
            'admin_emails_for_notifications': 'team@example.com', 'shop_lat': '14.5', 'shop_lng': '120.8',
            'max_saved_designs': '35', 'amount': '1200', 'free_radius_km': '20', 'per_km_rate': '40',
            'max_fee_cap': '0', 'notes': 'Updated logistics notes.'}

    def test_one_save_updates_every_section(self):
        response = self.client.post(reverse('admin_site_settings'), self.data)
        self.assertRedirects(response, reverse('admin_site_settings'))
        self.settings.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(self.settings.site_name, 'Updated business')
        self.assertEqual(self.settings.max_saved_designs, 35)
        self.assertEqual(self.settings.booking_overtime_rate, Decimal('550'))
        self.assertEqual(self.settings.updated_by, self.admin)
        self.assertEqual(self.config.amount, Decimal('1200'))
        self.assertEqual(self.config.shop_lat, Decimal('14.5'))
        self.assertEqual(self.config.notes, 'Updated logistics notes.')

    def test_invalid_section_never_partially_saves_other_sections(self):
        for changes in ({'max_saved_designs': '0'}, {'per_km_rate': '-1'}, {'shop_lat': '91'}, {'site_name': ''}):
            with self.subTest(changes=changes):
                response = self.client.post(reverse('admin_site_settings'), {**self.data, **changes})
                self.assertEqual(response.status_code, 400)
                self.settings.refresh_from_db()
                self.config.refresh_from_db()
                self.assertEqual(self.settings.site_name, 'Balloorina')
                self.assertEqual(self.settings.max_saved_designs, 20)
                self.assertEqual(self.config.amount, Decimal('1000'))
                self.assertEqual(self.config.shop_lat, Decimal('14.4'))
                self.assertContains(response, 'Updated logistics notes.', status_code=400)

    def test_page_orders_business_first_and_single_save_last(self):
        html = self.client.get(reverse('admin_site_settings')).content.decode()
        form = html[html.index('<form method="post" id="ss_form"'):]
        form = form[:form.index('</form>')]
        positions = [form.index(value) for value in ('Business Profile', 'Logistics &amp; Delivery', 'Design Settings',
            'Social Links', 'Booking Rules', 'Booking Duration &amp; Overtime', 'id="ss_btn_save"')]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(form.count('type="submit"'), 1)
        self.assertEqual(form.count('<form'), 1)
