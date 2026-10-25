"""Opt-in browser coverage: RUN_HOME_STATS_BROWSER=1, using isolated fixtures."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, HomeContent, Review, User


@skipUnless(os.environ.get('RUN_HOME_STATS_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class HomeStatisticsBrowserTests(StaticLiveServerTestCase):
    def test_home_values_animation_and_admin_support_hours(self):
        from playwright.sync_api import sync_playwright, expect

        root = Path(__file__).resolve().parent.parent
        artifacts = root / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        content = HomeContent.objects.create(stat_events_styled='500', stat_rating='100',
            stat_satisfaction='100', stat_response_time='24')
        admin = User.objects.create_user(username='home-stats-browser-admin', role='admin', email_verified=True)
        customer = User.objects.create_user(username='home-stats-browser-customer', role='customer')
        self.client.force_login(admin)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        def seed_reviews():
            for rating in (5, 4, 4, 3):
                booking = Booking.objects.create(user=customer, event_date=timezone.localdate() - timedelta(days=1),
                    event_time=time(10), status='completed', package_type='Test', total_price=1000)
                Review.objects.create(user=customer, booking=booking, rating=rating, comment='An event review.')
            for status in ('pending', 'confirmed', 'cancelled'):
                Booking.objects.create(user=customer, event_date=timezone.localdate() + timedelta(days=7),
                    event_time=time(10), status=status, package_type='Test', total_price=1000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce', viewport={'width': 1440, 'height': 1000})
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def go(path):
                page.goto(self.live_server_url + path, wait_until='domcontentloaded')

            def capture(name, selector):
                for theme in ('light', 'dark'):
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        panel = page.locator(selector)
                        panel.scroll_into_view_if_needed()
                        self.assertFalse(panel.evaluate('el => el.scrollWidth > el.clientWidth + 1'), f'{name}-{theme}-{width}')
                        page.screenshot(path=str(artifacts / f'home-stats-{name}-{theme}-{width}.png'), animations='disabled')

            try:
                go(reverse('home'))
                heads = page.locator('.stats-card h3')
                expect(heads).to_have_text(['0', 'No reviews yet', 'No reviews yet', '11 hrs/day'])
                capture('empty', '.stats-section')

                # Playwright owns an event loop; keep synchronous ORM work on a worker thread.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(seed_reviews).result()
                go(reverse('home'))
                expect(heads).to_have_text(['4', '4.0/5', '75%', '11 hrs/day'])
                capture('populated', '.stats-section')
                page.emulate_media(reduced_motion='no-preference')
                go(reverse('home'))
                page.locator('.stats-card').scroll_into_view_if_needed()
                expect(heads).to_have_text(['4', '4.0/5', '75%', '11 hrs/day'], timeout=7000)
                expect(page.locator('.stats-caption')).to_contain_text('Based on 4 customer reviews.')

                page.emulate_media(reduced_motion='reduce')
                context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
                go(reverse('admin_home_content'))
                expect(page.locator('#preview_events_styled')).to_have_value('4')
                expect(page.locator('#preview_customer_rating')).to_have_value('4.0/5')
                expect(page.locator('#preview_positive_reviews')).to_have_value('75%')
                for selector in ('#preview_events_styled', '#preview_customer_rating', '#preview_positive_reviews'):
                    expect(page.locator(selector)).not_to_be_editable()
                expect(page.locator('#support_hours')).to_have_value('11')
                capture('admin', 'form:has(#support_hours) .form-section')
                page.locator('#support_hours').fill('9')
                page.get_by_role('button', name='Save Support Hours', exact=True).click()
                expect(page.locator('#support_hours')).to_have_value('9')
                go(reverse('home'))
                expect(heads).to_have_text(['4', '4.0/5', '75%', '9 hrs/day'])
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
