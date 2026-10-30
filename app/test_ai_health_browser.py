import os
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AiRequest, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AiHealthBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        admin = User.objects.create_user(username='health-browser-admin', role='admin')
        customer = User.objects.create_user(username='health-browser-customer', role='customer')
        for index in range(10):
            job = AiRequest.objects.create(user=customer, input_text='PRIVATE HEALTH PROMPT', fingerprint='browser',
                state='failed' if index < 2 else 'succeeded', kind='generate',
                error_code='provider_credits' if index < 2 else '',
                metrics={'calls': [{'input_tokens': 79, 'output_tokens': 6}], 'quality': {'checked': True, 'passed': True}})
            AiRequest.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(hours=index+1))
        job = AiRequest.objects.create(user=customer, input_text='PRIVATE OLD PROMPT', fingerprint='browser', state='succeeded')
        AiRequest.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(days=10))
        self.client.force_login(admin)
        self.cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def context(self, browser, width=1440, height=1000, theme='light'):
        context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
        context.route('https://**', lambda route: route.fulfill(body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({}),DismissReason:{}};', content_type='application/javascript') if 'sweetalert' in route.request.url else route.abort())
        context.add_init_script('localStorage.setItem("theme", "'+theme+'")')
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.cookie, 'url': self.live_server_url}])
        return context

    def test_async_controls_retry_history_and_stale_response(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            context = self.context(browser)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url+reverse('ai_health'), wait_until='domcontentloaded')
            page.evaluate('window.healthDocumentSentinel = 123')
            expect(page.locator('.ah-request-table tbody tr')).to_have_count(8)
            page.get_by_role('link', name='Page 2', exact=True).click()
            expect(page.locator('.ah-request-table tbody tr')).to_have_count(2)
            expect(page.locator('#ahRequests [aria-current="page"]')).to_have_text('2')
            page.get_by_role('button', name='Rows per page: 8', exact=True).click()
            page.get_by_role('option', name='4', exact=True).click()
            expect(page.locator('.ah-request-table tbody tr')).to_have_count(4)
            expect(page.locator('#ahRequests [aria-current="page"]')).to_have_text('1')
            page.get_by_role('button', name='Filter request status: All statuses', exact=True).click()
            page.get_by_role('option', name='Failed', exact=True).click()
            expect(page.locator('.ah-request-table tbody tr')).to_have_count(2)
            # Table filters do not change the whole-period summary counts.
            expect(page.locator('.ah-metrics strong').first).to_have_text('10')
            search = page.get_by_role('searchbox', name='Search requests')
            search.fill('unmatched')
            expect(page.get_by_text('No matching requests', exact=True)).to_be_visible()
            expect(page.locator('.ah-request-table')).to_have_count(0)
            page.get_by_role('button', name='Clear filters', exact=True).click()
            expect(page.locator('.ah-request-table tbody tr')).to_have_count(4)
            page.get_by_role('button', name='Report period: Last 7 days', exact=True).click()
            page.get_by_role('option', name='Last 30 days', exact=True).click()
            expect(page.locator('.ah-metrics strong').first).to_have_text('11')
            self.assertEqual(page.evaluate('window.healthDocumentSentinel'), 123)
            page.go_back()
            expect(page.locator('.ah-metrics strong').first).to_have_text('10')
            # A failed refresh retains the last good report and can be retried.
            page.route('**/dashboard/ai-health/?**', lambda route: route.abort(), times=1)
            page.get_by_role('button', name='Refresh', exact=True).click()
            expect(page.locator('.ah-load-error')).to_be_visible()
            expect(page.locator('.ah-metrics strong').first).to_have_text('10')
            page.get_by_role('button', name='Try again', exact=True).click()
            expect(page.locator('.ah-load-error')).to_be_hidden()
            expect(page.locator('.ai-health')).not_to_have_attribute('aria-busy', 'true')
            # Hold an earlier search response, then type again before it returns.
            pending = []
            page.route('**/dashboard/ai-health/?**q=hold**', lambda route: pending.append(route))
            search.fill('hold')
            page.wait_for_function('document.querySelector(".ai-health").getAttribute("aria-busy") === "true"')
            search.fill('Image generation')
            expect(page.locator('.ah-request-table tbody tr')).to_have_count(4)
            expect(search).to_have_value('Image generation')
            expect(page).to_have_url(__import__('re').compile('q=Image[+%]'))
            for route in pending:
                try:
                    route.fulfill(json={'summary_html': 'STALE', 'results_html': 'STALE', 'filters': {}, 'checked_at': ''})
                except Exception:
                    pass  # Chromium may already have cancelled the superseded fetch.
            expect(search).to_have_value('Image generation')
            self.assertNotIn('STALE', page.locator('.ai-health').inner_text())
            self.assertNotIn('PRIVATE', page.locator('.ai-health').inner_text())
            self.assertEqual(errors, [])
            context.close()
            browser.close()

    def test_themes_responsive_focus_and_empty_period(self):
        from playwright.sync_api import sync_playwright, expect
        screenshots = Path(settings.BASE_DIR)/'.booking-followup-check'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for width, height in ((1440, 1000), (390, 844), (320, 640)):
                for theme in ('light', 'dark'):
                    with self.subTest(width=width, theme=theme):
                        context = self.context(browser, width, height, theme)
                        page = context.new_page()
                        page.goto(self.live_server_url+reverse('ai_health'), wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        expect(page.locator('.ai-health h1')).to_have_text('AI health')
                        expect(page.locator('.ah-alert').first).to_be_visible()
                        search = page.get_by_role('searchbox', name='Search requests')
                        search.focus()
                        self.assertEqual(search.evaluate('(el) => getComputedStyle(el).outlineWidth'), '2px')
                        self.assertLessEqual(page.locator('.ai-health').evaluate('(el) => el.scrollWidth-el.clientWidth'), 1)
                        page.locator('h1').scroll_into_view_if_needed()
                        page.screenshot(path=str(screenshots/f'ai-health-redesign-{width}-{theme}.png'), full_page=True)
                        page.get_by_role('button', name='Filter request status: All statuses', exact=True).click()
                        page.get_by_role('option', name='Queued', exact=True).click()
                        expect(page.get_by_text('No matching requests', exact=True)).to_be_visible()
                        self.assertLessEqual(page.locator('.ai-health').evaluate('(el) => el.scrollWidth-el.clientWidth'), 1)
                        context.close()
            browser.close()
