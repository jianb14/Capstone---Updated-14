"""Service-tool handoff, safe login continuation, and booking calendar parity."""
import json
from datetime import time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from .models import BlockedDate, Booking, SiteSettings, User


class ServiceQuizInputTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(User.objects.create_user(username='quiz-input', role='customer'))

    def submit(self, data):
        return self.client.post(reverse('theme_quiz_api'), json.dumps(data), content_type='application/json')

    @patch('app.views.public.get_chatbot_response', return_value={'text': '**Garden Glow**'})
    def test_custom_event_and_vibe_reach_ai(self, chatbot):
        response = self.submit({'event_type': 'Graduation', 'vibe': 'Garden party', 'colors': 'Pink, Gold'})
        self.assertTrue(response.json()['success'])
        prompt = chatbot.call_args.args[0]
        self.assertIn('Event type: Graduation', prompt)
        self.assertIn('Preferred vibe: Garden party', prompt)

    @patch('app.views.public.get_chatbot_response')
    def test_invalid_or_oversized_input_does_not_call_ai(self, chatbot):
        for payload in ([], None, {'event_type': 'Birthday', 'vibe': 'x' * 101},
                        {'event_type': 'x' * 101, 'vibe': 'Garden'},
                        {'event_type': 'Birthday', 'vibe': 'Garden', 'colors': 'x' * 61}):
            with self.subTest(payload=payload):
                self.assertEqual(self.submit(payload).status_code, 400)
        chatbot.assert_not_called()


class ServiceLoginContinuationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='service-customer', email='service@example.com',
            password='ServicePassword!23', role='customer', email_verified=True)

    def login(self, **extra):
        return self.client.post(reverse('login'), {'email': self.user.email,
            'password': 'ServicePassword!23', **extra})

    def test_all_service_booking_urls_survive_login(self):
        for source in ('estimate', 'availability', 'ai', 'packages'):
            with self.subTest(source=source):
                self.client.logout()
                destination = reverse('booking_page') + f'?from={source}&package_id=12&event_date=2099-01-15'
                response = self.client.get(destination)
                self.assertEqual(response.status_code, 302)
                self.client.get(response.url)
                response = self.login()
                self.assertRedirects(response, destination, fetch_redirect_response=False)

    def test_failed_login_keeps_destination_and_hidden_field(self):
        destination = reverse('booking_page') + '?from=estimate&addon_id=5'
        response = self.client.get(reverse('login'), {'next': destination})
        self.assertContains(response, 'name="next"')
        response = self.client.post(reverse('login'), {'email': self.user.email, 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['login_return_to'], destination)
        self.assertRedirects(self.login(), destination, fetch_redirect_response=False)

    def test_ai_login_returns_to_quiz_anchor(self):
        destination = reverse('services') + '#style-quiz'
        self.client.get(reverse('login'), {'next': destination})
        self.assertRedirects(self.login(), destination, fetch_redirect_response=False)

    def test_rejects_external_and_script_destinations(self):
        for destination in ('https://evil.example/booking/', '//evil.example/', 'javascript:alert(1)',
                            '/\\evil.example/', 'https://testserver.evil.example/'):
            with self.subTest(destination=destination):
                self.client.logout()
                self.client.get(reverse('login'), {'next': destination})
                self.assertRedirects(self.login(next=destination), reverse('home'), fetch_redirect_response=False)

    def test_admin_keeps_dashboard_destination(self):
        self.user.role = 'admin'
        self.user.save(update_fields=['role'])
        self.client.get(reverse('login'), {'next': reverse('booking_page') + '?from=estimate'})
        self.assertRedirects(self.login(), reverse('dashboard'), fetch_redirect_response=False)
        self.assertNotIn('login_return_to', self.client.session)


class ServiceAvailabilityParityTests(TestCase):
    def setUp(self):
        self.day = timezone.localdate() + timedelta(days=30)
        self.user = User.objects.create_user(username='calendar-customer', role='customer')
        self.url = reverse('check_date_availability')

    def booking(self, start, end, **extra):
        return Booking.objects.create(user=self.user, event_date=self.day, event_time=time(start),
            event_end_time=time(end), package_type='Test', total_price=100, status='confirmed', **extra)

    def check(self, day=None):
        return self.client.get(self.url, {'date': (day or self.day).isoformat()}).json()

    def test_partial_day_stays_available(self):
        self.booking(10, 13)
        self.assertTrue(self.check()['available'])

    def test_union_of_adjacent_bookings_is_fully_booked(self):
        self.booking(7, 12)
        self.booking(12, 18)
        result = self.check()
        self.assertFalse(result['available'])
        self.assertIn('fully booked', result['message'])
        self.assertEqual(len(result['suggestions']), 3)

    def test_gap_between_bookings_is_not_fully_booked(self):
        self.booking(7, 10)
        self.booking(13, 18)
        self.assertTrue(self.check()['available'])

    def test_blocked_and_lead_dates_are_excluded_from_suggestions(self):
        settings = SiteSettings.load()
        settings.booking_lead_time_days = 5
        settings.save()
        BlockedDate.objects.create(date=timezone.localdate() + timedelta(days=5), reason='Unavailable')
        result = self.check(timezone.localdate())
        self.assertFalse(result['available'])
        self.assertEqual(result['suggestions'][0], (timezone.localdate() + timedelta(days=6)).isoformat())

    @patch('app.views.public.get_booking_form_availability')
    def test_overnight_and_temporary_hold_ranges_are_used(self, availability):
        availability.return_value = {'blockedDates': [], 'bookedRanges': {
            self.day.isoformat(): [[0, 600], [600, 1080]],
        }}
        self.assertFalse(self.check()['available'])

    def test_services_calendar_exposes_no_customer_details(self):
        self.booking(7, 18)
        BlockedDate.objects.create(date=self.day + timedelta(days=1), reason='Maintenance')
        response = self.client.get(reverse('services'))
        data = response.context['availability_data']
        self.assertEqual(data['bookedRanges'][self.day.isoformat()], [[420, 1080]])
        self.assertNotIn(self.user.username, str(data))
        self.assertContains(response, 'booking_picker_a.js')
        self.assertEqual(response.context['services_widget_data']['bookingUrl'], reverse('booking_page'))
