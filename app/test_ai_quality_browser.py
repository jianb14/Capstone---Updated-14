import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import AiRequest, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AiQualityBrowserTests(StaticLiveServerTestCase):
    def test_gallery_memory_and_health_in_both_themes_and_sizes(self):
        from playwright.sync_api import sync_playwright, expect
        customer = User.objects.create_user(username='quality-browser', role='customer')
        admin = User.objects.create_user(username='quality-admin-browser', role='admin')
        AiRequest.objects.create(user=customer, input_text='Private customer message', fingerprint='test', state='failed',
            error_code='provider_credits', metrics={'calls': [{'input_tokens': 20, 'output_tokens': 10, 'estimated_usd': None}]})
        screenshots = Path(settings.BASE_DIR)/'.booking-followup-check'
        screenshots.mkdir(exist_ok=True)
        self.client.force_login(admin)
        admin_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.client.force_login(customer)
        customer_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                for width, height in ((1440, 1000), (390, 844), (320, 640)):
                    for theme in ('light', 'dark'):
                        with self.subTest(width=width, theme=theme):
                            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                            errors, cleared = [], []
                            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                'value': admin_cookie, 'url': self.live_server_url}])
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(self.live_server_url+reverse('ai_health'), wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            expect(page.locator('.ai-health h1')).to_have_text('AI health')
                            expect(page.locator('.ah-alert').first).to_be_visible()
                            self.assertNotIn('Private customer message', page.locator('.ai-health').inner_text())
                            self.assertLessEqual(page.locator('.ai-health').evaluate('(el) => el.scrollWidth-el.clientWidth'), 1)
                            page.screenshot(path=str(screenshots/f'ai-health-{width}-{theme}.png'), animations='disabled')
                            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                'value': customer_cookie, 'url': self.live_server_url}])
                            def api(route):
                                url = route.request.url
                                if route.request.method == 'DELETE' and '/brief/' in url:
                                    cleared.append(True)
                                    route.fulfill(json={'brief': {}, 'version': 1})
                                elif route.request.method == 'POST' and '/api/ai/requests/' in url:
                                    payload = route.request.post_data_json
                                    route.fulfill(json={'id': payload['request_id'], 'state': 'succeeded', 'session_id': 1,
                                        'input_text': payload['message'], 'has_design_brief': True,
                                        'result': {'session_id': 1, 'response': 'Here are actual setups from our Gallery.',
                                        'gallery': [{'id': 1, 'url': '/media/gallery/quality.png',
                                            'caption': '<img src=x onerror=alert(1)> Garden wedding', 'label': 'Actual setup'}]}})
                                elif url.endswith('/active/'):
                                    route.fulfill(json={'request': None})
                                elif url.endswith('/sessions/'):
                                    route.fulfill(json={'sessions': [{'id': 1, 'title': 'Actual setups'}]})
                                else:
                                    route.fulfill(json={'messages': []})
                            context.route('**/api/ai/**', api)
                            context.route('**/api/chat/**', api)
                            context.route('**/media/gallery/quality.png', lambda route: route.fulfill(
                                path=str(Path(settings.BASE_DIR)/'static/images/sustainable.png'), content_type='image/png'))
                            page.goto(self.live_server_url+reverse('home'), wait_until='domcontentloaded')
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('#ai-fab').click()
                            page.locator('#ai-widget-input').fill('Show actual wedding setups')
                            page.locator('#ai-widget-send').click()
                            expect(page.locator('.ai-gallery-results figure')).to_have_count(1)
                            expect(page.locator('.ai-gallery-results small')).to_have_text('Actual setup')
                            expect(page.locator('.ai-gallery-results figcaption img')).to_have_count(0)
                            expect(page.locator('.ai-image-book-btn, .ai-design-actions, .ai-feedback-row')).to_have_count(0)
                            expect(page.get_by_role('link', name='View gallery')).to_have_attribute('href', '/gallery/')
                            self.assertLessEqual(page.locator('#ai-widget').evaluate('(el) => el.scrollWidth-el.clientWidth'), 1)
                            page.screenshot(path=str(screenshots/f'ai-actual-gallery-{width}-{theme}.png'), animations='disabled')
                            page.locator('#ai-guide-open').click()
                            page.get_by_role('button', name='Clear saved details').click()
                            expect(page.get_by_role('button', name='Clear saved details')).to_be_hidden()
                            self.assertEqual(cleared, [True])
                            self.assertEqual(errors, [])
                            context.close()
            finally:
                browser.close()
