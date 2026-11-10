"""Opt-in real-browser verification: RUN_ERROR_PAGES_BROWSER=1."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings


@skipUnless(os.environ.get('RUN_ERROR_PAGES_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(ROOT_URLCONF='app.test_error_pages', DEBUG=False, SECURE_SSL_REDIRECT=False,
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   REQUEST_RATE_LIMITING_ENABLED=False)
class ErrorPageBrowserTests(StaticLiveServerTestCase):
    def test_layout_themes_assets_keyboard_and_recovery_links(self):
        from playwright.sync_api import expect, sync_playwright

        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check' / 'error-pages'
        artifacts.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(reduced_motion='reduce')
            context.add_init_script("localStorage.setItem('balloorina-theme', 'dark')")
            page = context.new_page()
            errors, failed_assets = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('requestfailed', lambda request: failed_assets.append(request.url))
            try:
                for path, status in (('/_errors/forbidden/', 403), ('/not-a-page/', 404), ('/_errors/broken/', 500)):
                    response = page.goto(self.live_server_url + path, wait_until='networkidle')
                    self.assertEqual(response.status, status)
                    page.evaluate('document.fonts.ready')
                    self.assertTrue(page.locator('.error-brand img').evaluate('img => img.complete && img.naturalWidth > 0'))
                    self.assertTrue(page.evaluate("document.fonts.check('500 16px Montserrat')"))
                    for theme in ('dark', 'light'):
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        for width, height in ((1440, 900), (1024, 768), (768, 1024), (390, 844), (320, 568), (640, 360)):
                            page.set_viewport_size({'width': width, 'height': height})
                            expect(page.get_by_role('heading', level=1)).to_be_visible()
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                            for link in page.locator('.error-actions a').all():
                                bounds = link.bounding_box()
                                self.assertGreaterEqual(bounds['height'], 44)
                                self.assertGreaterEqual(bounds['x'], 0)
                                self.assertLessEqual(bounds['x'] + bounds['width'], width)
                            # Readable muted copy in both themes (WCAG normal-text contrast).
                            contrast = page.locator('.error-message').evaluate('''element => {
                                const rgb = value => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
                                const luminance = values => values.map(v => {
                                    v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
                                }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
                                const a = luminance(rgb(getComputedStyle(element).color));
                                const b = luminance(rgb(getComputedStyle(document.body).backgroundColor));
                                return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
                            }''')
                            self.assertGreaterEqual(contrast, 4.5)
                            if width in (1440, 768, 390, 320):
                                page.screenshot(path=str(artifacts / f'{status}-{theme}-{width}.png'), full_page=True)
                    # Tab order reaches the brand followed by the real recovery links.
                    page.set_viewport_size({'width': 1440, 'height': 900})
                    page.locator('body').click(position={'x': 1, 'y': 1})
                    page.keyboard.press('Tab')
                    expect(page.get_by_role('link', name='Balloorina home')).to_be_focused()
                    page.keyboard.press('Tab')
                    expect(page.get_by_role('link', name='Back to Home')).to_be_focused()
                    self.assertEqual(page.get_by_role('link', name='Back to Home').evaluate('el => getComputedStyle(el).outlineStyle'), 'solid')
                    with page.expect_navigation(wait_until='domcontentloaded') as navigation:
                        page.get_by_role('link', name='Back to Home').click()
                    self.assertEqual(navigation.value.status, 200)
                    self.assertEqual(page.url, self.live_server_url + '/')

                for path, label, destination in (('/_errors/denied/', 'Sign In', '/login/'),
                                                  ('/not-a-page/', 'Explore Services', '/services/'),
                                                  ('/_errors/broken/', 'Try Again', '/_errors/broken/')):
                    page.goto(self.live_server_url + path, wait_until='domcontentloaded')
                    with page.expect_request(self.live_server_url + destination) as request:
                        page.get_by_role('link', name=label, exact=True).click()
                    self.assertEqual(request.value.method, 'GET')
                    page.wait_for_load_state('domcontentloaded')
                    self.assertEqual(page.url, self.live_server_url + destination)
                self.assertEqual(errors, [])
                self.assertEqual(failed_assets, [])
            finally:
                context.close()
                browser.close()

    def test_error_page_remains_usable_without_scripts_or_static_assets(self):
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(java_script_enabled=False, viewport={'width': 320, 'height': 568})
            context.route('**/static/**', lambda route: route.abort())
            page = context.new_page()
            try:
                for path, status in (('/_errors/denied/', 403), ('/missing-page/', 404), ('/_errors/broken/', 500)):
                    response = page.goto(self.live_server_url + path, wait_until='domcontentloaded')
                    self.assertEqual(response.status, status)
                    expect(page.get_by_role('heading', level=1)).to_be_visible()
                    expect(page.get_by_role('link', name='Back to Home')).to_have_attribute('href', '/')
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            finally:
                context.close()
                browser.close()
