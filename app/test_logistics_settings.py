from datetime import date, time
from decimal import Decimal
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from .models import Booking, ServiceChargeConfig, SiteSettings, User


class LogisticsSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(username='logistics-admin', role='admin')
        self.client.force_login(self.admin)
        self.config = ServiceChargeConfig.objects.create(pk=1, amount=1000, notes='Travel and styling.',
            shop_lat='14.414', shop_lng='120.982', free_radius_km=15, per_km_rate=30)
        self.data = {'settings_section': 'logistics', 'amount': '1200.00', 'free_radius_km': '20',
                     'per_km_rate': '45', 'max_fee_cap': '5000', 'notes': 'Updated inclusions.'}

    def test_rates_live_in_site_settings_and_old_package_form_is_removed(self):
        response = self.client.get(reverse('admin_site_settings'))
        self.assertContains(response, 'id="logistics-settings"')
        self.assertContains(response, 'Save Settings')
        response = self.client.get(reverse('admin_package_list'))
        self.assertNotContains(response, 'name="service_charge_amount"')
        # Packages no longer display the removed logistics-settings shortcut.
        self.assertNotContains(response, '#logistics-settings')

    def test_rate_save_preserves_business_settings_shop_pin_and_booked_quote(self):
        settings = SiteSettings.load()
        settings.site_name = 'Keep this name'
        settings.save()
        booking = Booking.objects.create(user=self.admin, event_date=date(2099, 1, 1),
            event_time=time(10), event_location='Venue', total_price=6000, logistics_fee=1000)
        response = self.client.post(reverse('admin_site_settings'), self.data)
        self.assertRedirects(response, reverse('admin_site_settings') + '#logistics-settings')
        self.config.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.config.amount, Decimal('1200'))
        self.assertEqual(self.config.shop_lat, Decimal('14.414'))
        self.assertEqual(self.config.per_km_rate, Decimal('45'))
        self.assertEqual(self.config.notes, 'Updated inclusions.')
        self.assertEqual(booking.logistics_fee, Decimal('1000'))
        self.assertEqual(SiteSettings.load().site_name, 'Keep this name')

    def test_invalid_rates_keep_entered_values_and_do_not_save(self):
        for invalid in ('-1', 'NaN', 'Infinity', '100000000'):
            with self.subTest(invalid=invalid):
                response = self.client.post(reverse('admin_site_settings'), {**self.data, 'per_km_rate': invalid})
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, 'Updated inclusions.', status_code=400)
                self.config.refresh_from_db()
                self.assertEqual(self.config.amount, Decimal('1000'))
                self.assertEqual(self.config.per_km_rate, Decimal('30'))

    def test_client_note_displays_current_rates_in_all_three_sections(self):
        response = self.client.get(reverse('package'))
        for text in ('Within Cavite:', 'Outside Cavite:', 'minimum of 1 billable km',
                     'included 15 km', 'straight line', 'Travel and styling.'):
            self.assertContains(response, text, count=3)
        self.config.per_km_rate = 0
        self.config.max_fee_cap = 2000
        self.config.save()
        response = self.client.get(reverse('package'))
        self.assertContains(response, 'No additional distance charge currently applies.', count=3)
        self.assertContains(response, 'The total is capped at', count=3)

    def test_logistics_settings_require_admin_role(self):
        customer = User.objects.create_user(username='logistics-customer', role='customer')
        self.client.force_login(customer)
        self.assertEqual(self.client.post(reverse('admin_site_settings'), self.data).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_service_charge_update'), self.data).status_code, 403)
