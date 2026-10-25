"""Customers served counts completed customers and cannot be manually overridden."""
from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .home_statistics import get_customers_served
from .models import AboutContent, Booking, User


class AboutStatisticsTests(TestCase):
    def setUp(self):
        # The journey data migration creates an About row; use explicit fixtures.
        AboutContent.objects.all().delete()
        self.customer = User.objects.create_user(username='about-customer', role='customer')

    def booking(self, user=None, status='completed'):
        return Booking.objects.create(
            user=user or self.customer, status=status,
            event_date=timezone.localdate() - timedelta(days=1), event_time=time(10),
            package_type='Test Package', total_price=1000,
        )

    def test_empty_about_ignores_old_marketing_values(self):
        AboutContent.objects.create(story_stat_number='1,000+', story_stat_text='People trust Balloorina.ph.')
        response = self.client.get(reverse('about'))
        self.assertEqual(response.context['customers_served'], 0)
        self.assertContains(response, '<strong>0</strong>', html=True)
        self.assertContains(response, 'Customers Served')
        self.assertNotContains(response, '1,000+')
        self.assertNotContains(response, 'People trust Balloorina.ph.')

    def test_unique_customers_with_completed_bookings_only(self):
        for _ in range(3):
            self.booking()
        second = User.objects.create_user(username='about-second', role='customer')
        self.booking(user=second)
        third = User.objects.create_user(username='about-pending', role='customer')
        for status in ('pending', 'pending_payment', 'confirmed', 'cancelled', 'denied'):
            self.booking(user=third, status=status)
        User.objects.create_user(username='about-no-booking', role='customer')
        self.assertEqual(get_customers_served(), 2)
        self.assertEqual(self.client.get(reverse('about')).context['customers_served'], 2)

    def test_count_updates_after_booking_status_changes(self):
        booking = self.booking(status='confirmed')
        self.assertEqual(self.client.get(reverse('about')).context['customers_served'], 0)
        booking.status = 'completed'
        booking.save(update_fields=['status'])
        self.assertEqual(self.client.get(reverse('about')).context['customers_served'], 1)
        booking.status = 'cancelled'
        booking.save(update_fields=['status'])
        self.assertEqual(self.client.get(reverse('about')).context['customers_served'], 0)

    def test_admin_shows_same_readonly_count_and_ignores_spoofed_statistics(self):
        content = AboutContent.objects.create(story_stat_number='old', story_stat_text='Old label')
        self.booking()
        admin = User.objects.create_user(username='about-admin', role='admin')
        self.client.force_login(admin)
        url = reverse('admin_about_content')
        response = self.client.get(url)
        self.assertEqual(response.context['customers_served'], 1)
        self.assertContains(response, 'id="preview_customers_served" value="1" class="form-control" readonly')
        self.assertNotContains(response, 'name="story_stat_number"')
        self.assertNotContains(response, 'name="story_stat_text"')
        response = self.client.post(url, {
            'story_stat_number': '9999', 'story_stat_text': 'Fake customers',
            'story_title': 'Updated story',
        })
        self.assertRedirects(response, url)
        content.refresh_from_db()
        self.assertEqual(content.story_stat_number, 'old')
        self.assertEqual(content.story_stat_text, 'Old label')
        self.assertEqual(content.story_title, 'Updated story')
        self.assertEqual(self.client.get(reverse('about')).context['customers_served'], 1)

    def test_fresh_about_does_not_seed_a_manual_statistic(self):
        self.client.get(reverse('about'))
        content = AboutContent.objects.get()
        self.assertEqual(content.story_stat_number, '')
        self.assertEqual(content.story_stat_text, '')
