"""Automatic public statistics and the admin's editable daily support hours."""
from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .home_statistics import get_home_statistics
from .models import Booking, HomeContent, Review, User


class HomeStatisticsTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='stats-customer', role='customer')

    def booking(self, status='completed'):
        return Booking.objects.create(user=self.customer, status=status,
            event_date=timezone.localdate() - timedelta(days=1), event_time=time(10),
            package_type='Test Package', total_price=1000)

    def review(self, rating, **extra):
        return Review.objects.create(user=self.customer, booking=self.booking(), rating=rating,
            comment='Customer review', **extra)

    def test_empty_home_has_real_zero_and_no_invented_reviews(self):
        response = self.client.get(reverse('home'))
        stats = response.context['home_stats']
        self.assertEqual(stats['events_styled'], 0)
        self.assertEqual(stats['review_count'], 0)
        self.assertIsNone(stats['customer_rating'])
        self.assertIsNone(stats['positive_reviews'])
        self.assertEqual(response.context['support_hours'], 11)
        self.assertContains(response, 'No reviews yet')
        self.assertNotContains(response, '500+')

    def test_only_completed_bookings_count(self):
        self.booking()
        self.booking()
        for status in ('pending', 'pending_payment', 'confirmed', 'cancelled', 'denied'):
            self.booking(status)
        self.assertEqual(get_home_statistics()['events_styled'], 2)

    def test_all_valid_reviews_count_and_invalid_ratings_are_excluded(self):
        self.review(5, is_testimonial=True, is_featured=True)
        for rating in (4, 3, 1, 0, 100):
            self.review(rating)
        stats = get_home_statistics()
        self.assertEqual(stats['review_count'], 4)
        self.assertEqual(stats['customer_rating'], Decimal('3.3'))
        self.assertEqual(stats['positive_reviews'], Decimal('50.0'))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Based on 4 customer reviews.')
        self.assertEqual(response.context['home_stats'], stats)

    def test_zero_positive_reviews_is_zero_percent_not_an_empty_state(self):
        self.review(1)
        self.review(2)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['home_stats']['positive_reviews'], Decimal('0.0'))
        self.assertNotContains(response, 'No reviews yet')

    def test_changes_to_bookings_and_reviews_show_on_next_request(self):
        booking = self.booking('confirmed')
        self.assertEqual(self.client.get(reverse('home')).context['home_stats']['events_styled'], 0)
        booking.status = 'completed'
        booking.save(update_fields=['status'])
        review = Review.objects.create(user=self.customer, booking=booking, rating=5, comment='Good')
        stats = self.client.get(reverse('home')).context['home_stats']
        self.assertEqual(stats['events_styled'], 1)
        self.assertEqual(stats['customer_rating'], Decimal('5.0'))
        review.rating = 2
        review.save(update_fields=['rating'])
        stats = self.client.get(reverse('home')).context['home_stats']
        self.assertEqual(stats['customer_rating'], Decimal('2.0'))
        self.assertEqual(stats['positive_reviews'], Decimal('0.0'))

    def test_old_manual_values_do_not_override_statistics_or_support_hours(self):
        HomeContent.objects.create(stat_events_styled='500', stat_rating='100',
            stat_satisfaction='100', stat_response_time='24')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['home_stats']['events_styled'], 0)
        self.assertEqual(response.context['support_hours'], 11)
        self.assertContains(response, 'No reviews yet')
        self.assertNotContains(response, 'Response Time')
        self.assertNotContains(response, 'Satisfaction Rate')


class HomeStatisticsAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='stats-admin', role='admin')
        self.client.force_login(self.admin)
        self.content = HomeContent.objects.create(stat_events_styled='500', stat_rating='100',
            stat_satisfaction='100', stat_response_time='24')
        self.url = reverse('admin_home_content')

    def test_admin_and_home_share_statistics_and_only_support_hours_is_editable(self):
        admin = self.client.get(self.url)
        home = self.client.get(reverse('home'))
        self.assertEqual(admin.context['home_stats'], home.context['home_stats'])
        self.assertContains(admin, 'Edit Support hours')
        dialog = self.client.get(reverse('admin_content_action', args=('home', 'support', 'section', self.content.pk)))
        self.assertIn('name="support_hours"', dialog.json()['html'])
        for field in ('stat_events_styled', 'stat_rating', 'stat_satisfaction', 'stat_response_time'):
            self.assertNotContains(admin, f'name="{field}"')

    def test_support_hours_saves_and_spoofed_statistics_are_ignored(self):
        response = self.client.post(self.url, {'support_hours': '9', 'stat_events_styled': '999',
            'stat_rating': '100', 'stat_satisfaction': '100', 'stat_response_time': '48'})
        self.assertRedirects(response, self.url)
        self.content.refresh_from_db()
        self.assertEqual(self.content.support_hours, 9)
        self.assertEqual(self.content.stat_events_styled, '500')
        self.assertEqual(self.content.stat_response_time, '24')
        self.assertEqual(self.client.get(reverse('home')).context['support_hours'], 9)

    def test_invalid_support_hours_does_not_save_other_changes(self):
        for invalid in ('', '0', '-1', '25', '11.5', 'abc'):
            with self.subTest(value=invalid):
                self.client.post(self.url, {'support_hours': invalid, 'hero_title': 'Must not save'})
                self.content.refresh_from_db()
                self.assertEqual(self.content.support_hours, 11)
                self.assertNotEqual(self.content.hero_title, 'Must not save')

    def test_other_home_forms_preserve_support_hours(self):
        self.content.support_hours = 7
        self.content.save(update_fields=['support_hours'])
        self.client.post(self.url, {'hero_title': 'A new hero title'})
        self.content.refresh_from_db()
        self.assertEqual(self.content.support_hours, 7)
        self.assertEqual(self.content.hero_title, 'A new hero title')
