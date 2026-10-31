"""Render the real auth templates and exercise validation without sending accounts or email."""
import mimetypes
import os
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


@skipUnless(os.environ.get('RUN_AUTH_BROWSER') == '1', 'Optional Playwright verification')
class AuthFormBrowserTests(SimpleTestCase):
    def test_fields_errors_checkboxes_and_floating_decorations(self):
        from playwright.sync_api import expect, sync_playwright

        pages = {}
        for name in ('login', 'register', 'forgot_password', 'reset_password', 'resend_verification'):
            request = RequestFactory().get('/' + name + '/')
            request.user = AnonymousUser()
            request.session = {}
            pages['/' + name + '/'] = render_to_string('auth/' + name + '.html',
                {'is_valid_link': True}, request=request)
        static_root = Path(settings.BASE_DIR) / 'static'
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc != 'auth.test':
                route.abort(); return
            if url.path in pages:
                route.fulfill(content_type='text/html', body=pages[url.path]); return
            if url.path.startswith('/static/'):
                path = (static_root / url.path.removeprefix('/static/')).resolve()
                if path.is_relative_to(static_root.resolve()) and path.is_file():
                    route.fulfill(content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream', body=path.read_bytes()); return
            route.abort()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                context = browser.new_context(reduced_motion='no-preference')
                context.route('**/*', serve)
                page = context.new_page(); errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for theme in ('light', 'dark'):
                    for width in (1440, 820, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 900})
                        for name in ('login', 'register', 'forgot_password', 'reset_password', 'resend_verification'):
                            page.goto('https://auth.test/' + name + '/', wait_until='load')
                            page.evaluate('''theme=>{
                                document.documentElement.dataset.theme=theme;
                                document.addEventListener('submit',event=>event.preventDefault(),true);
                            }''', theme)
                            expect(page.locator('.balloon')).to_have_count(8 if width < 641 else 29)
                            if name == 'login':
                                expect(page.locator('#loginForm label .auth-required')).to_have_count(0)
                            if width >= 641:
                                expect(page.locator('.balloon--auth-edge')).to_have_count(6)
                                bands = page.locator('.auth-scene').evaluate('''scene=>{
                                    const form=scene.querySelector('.auth-container').getBoundingClientRect();
                                    return [...scene.querySelectorAll('.balloon--auth-edge')].map(el=>{
                                        const box=el.getBoundingClientRect();
                                        return {above:box.bottom<form.top-6,below:box.top>form.bottom+6,
                                            centered:box.left>form.left && box.right<form.right};
                                    });
                                }''')
                                self.assertEqual(sum(band['above'] for band in bands),3,bands)
                                self.assertEqual(sum(band['below'] for band in bands),3,bands)
                                self.assertTrue(all(band['centered'] for band in bands),bands)
                            self.assertEqual(page.locator('.balloon img').evaluate_all(
                                'images=>new Set(images.map(image=>image.src)).size'), 6)
                            expect(page.locator('.hero-balloons')).to_have_attribute('aria-hidden', 'true')
                            expect(page.locator('.hero-balloons')).to_have_css('pointer-events', 'none')
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth-innerWidth'), 1)
                            normal_border = 'rgb(206, 206, 206)' if theme == 'light' else 'rgb(74, 74, 74)'
                            normal_ring = 'rgba(105, 105, 105, 0.4)' if theme == 'light' else 'rgba(153, 153, 153, 0.45)'
                            red = 'rgb(184, 53, 60)' if theme == 'light' else 'rgb(241, 145, 145)'
                            red_ring = 'rgba(184, 53, 60, 0.4)' if theme == 'light' else 'rgba(241, 145, 145, 0.4)'
                            fields = page.locator('.field-group input[required]')
                            first = fields.first
                            initial = first.evaluate('''el=>{el.focus();const s=getComputedStyle(el);return [s.borderColor,s.outlineColor,s.outlineWidth];}''')
                            self.assertEqual(initial, [normal_border, normal_ring, '2px'])
                            form = first.locator('xpath=ancestor::form')
                            form.dispatch_event('submit', {'bubbles': True, 'cancelable': True})
                            for index in range(fields.count()):
                                field = fields.nth(index)
                                expect(field).to_have_attribute('aria-invalid', 'true')
                                field.focus()
                                expect(field).to_have_css('border-color', red)
                                expect(field).to_have_css('outline-color', red_ring)
                                error = page.locator('#' + field.get_attribute('aria-describedby'))
                                expect(error).to_be_visible(); expect(error).to_have_css('color', red)
                                self.assertNotIn('*', error.inner_text())
                            check = page.locator('input[type="checkbox"]')
                            if check.count():
                                expect(check).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                                check.check()
                                expect(check).to_have_css('background-color', 'rgb(24, 24, 24)' if theme == 'light' else 'rgb(245, 245, 245)')
                                check.uncheck()
                                expect(check).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                            for index in range(fields.count()):
                                field = fields.nth(index)
                                field_id = field.get_attribute('id')
                                value = 'auth@example.com' if field_id == 'email' and name != 'register' else 'auth@gmail.com' if field_id == 'email' else 'ValidPassword!25' if 'password' in field_id else '09123456789' if field_id == 'phone' else 'Sample'
                                field.fill(value)
                                expect(field).to_have_attribute('aria-invalid', 'false')
                                expect(field).to_have_css('border-color', normal_border)
                                expect(field).to_have_css('outline-color', normal_ring)
                            if width in (1440, 390) and name in ('login', 'register', 'reset_password'):
                                page.screenshot(path=str(artifacts / f'auth-{name}-{theme}-{width}.png'), full_page=True)
                page.emulate_media(reduced_motion='reduce')
                expect(page.locator('.hero-balloons')).to_have_css('pointer-events', 'none')
                self.assertEqual(page.locator('.hero-balloons').evaluate('el=>el.getAnimations({subtree:true}).length'), 0)
                self.assertEqual(errors, [])
            finally:
                browser.close()
