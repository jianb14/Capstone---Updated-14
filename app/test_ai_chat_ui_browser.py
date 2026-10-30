"""Verify assistant presentation against the existing admin field treatment."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class AIChatUIBrowserTests(StaticLiveServerTestCase):
    def test_reference_rings_resizing_and_history_image_preview(self):
        from playwright.sync_api import expect, sync_playwright

        admin = User.objects.create_user(username='ai-ui-admin', role='admin', email_verified=True)
        self.client.force_login(admin)
        cookie = {'name': settings.SESSION_COOKIE_NAME,
                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                  'url': self.live_server_url}
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        field_style = '''el => {
            const s = getComputedStyle(el);
            return Object.fromEntries(['outlineWidth', 'outlineColor', 'outlineStyle',
                'outlineOffset', 'borderTopColor', 'boxShadow'].map(key => [key, s[key]]));
        }'''
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                for theme in ('light', 'dark'):
                    with self.subTest(theme=theme):
                        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                        context.add_cookies([cookie])
                        for domain in ('fonts.googleapis.com', 'fonts.gstatic.com', 'cdnjs.cloudflare.com'):
                            context.route(f'https://{domain}/**', lambda route: route.abort())
                        posts, errors = [], []

                        def api(route):
                            if route.request.method == 'POST':
                                posts.append(route.request.url)
                            url = route.request.url
                            if url.endswith('/sessions/'):
                                route.fulfill(json={'sessions': [{'id': 1, 'title': 'Saved design'}]})
                            elif '/history/' in url:
                                route.fulfill(json={'messages': [{'id': 12, 'role': 'assistant',
                                    'content': 'Your saved design. <img src="/media/ai_generated/ui-preview.png" alt="Balloorina Design Concept" data-ai-prompt="Birthday backdrop" style="max-width:100%;">',
                                    'ai_images': [{'id': 'ui-preview', 'url': '/media/ai_generated/ui-preview.png'}]}]})
                            elif url.endswith('/active/'):
                                route.fulfill(json={'request': None})
                            else:
                                route.fulfill(json={})

                        context.route('**/api/chat/**', api)
                        context.route('**/api/ai/**', api)
                        context.route('**/media/ai_generated/ui-preview.png', lambda route: route.fulfill(
                            path=str(Path(settings.BASE_DIR) / 'static/images/service_birthday.png'), content_type='image/png'))
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(self.live_server_url + reverse('admin_concerns'), wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        reference = page.locator('.ac-search input')
                        reference.focus()
                        expected_style = reference.evaluate(field_style)

                        page.goto(self.live_server_url + reverse('home'), wait_until='domcontentloaded')
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        page.locator('#ai-fab').click()
                        composer = page.locator('#ai-widget-input')
                        composer.focus()
                        self.assertEqual(page.locator('#ai-widget .ai-input-area').evaluate(field_style), expected_style)
                        expect(page.locator('#ai-widget-photo svg circle')).to_have_count(1)

                        row = page.locator('.ai-recent-chat-item.active')
                        expect(row).to_be_visible()
                        self.assertNotEqual(row.evaluate('el => getComputedStyle(el).backgroundColor'), 'rgb(255, 255, 255)')
                        delete, icon = row.locator('.ai-recent-chat-delete').bounding_box(), row.locator('.ai-recent-chat-delete svg').bounding_box()
                        for axis, dimension in (('x', 'width'), ('y', 'height')):
                            self.assertAlmostEqual(delete[axis] + delete[dimension] / 2, icon[axis] + icon[dimension] / 2, delta=1)
                        row_box = row.bounding_box()
                        self.assertAlmostEqual(row_box['y'] + row_box['height'] / 2, delete['y'] + delete['height'] / 2, delta=1)

                        # A draft reflows when crossing breakpoints, without losing its value.
                        draft = 'A birthday celebration with flowers, gold balloons and a backdrop. ' * 3
                        composer.fill(draft)
                        for width, height in ((1440, 1000), (390, 844), (320, 640), (600, 500)):
                            page.set_viewport_size({'width': width, 'height': height})
                            for short_draft in ('', 'Hello'):
                                composer.fill(short_draft)
                                expect(composer).to_have_css('height', '36px')
                                if width > 480:
                                    line_center = composer.evaluate('''el => {
                                        const style = getComputedStyle(el);
                                        return el.getBoundingClientRect().y + parseFloat(style.paddingTop) + parseFloat(style.lineHeight) / 2;
                                    }''')
                                    for selector in ('#ai-widget-photo', '#ai-widget-mic', '#ai-widget-send'):
                                        control = page.locator(selector).bounding_box()
                                        self.assertAlmostEqual(line_center, control['y'] + control['height'] / 2, delta=1)
                            page.screenshot(path=str(artifacts / f'ai-composer-single-line-{width}-{theme}.png'), animations='disabled')
                            composer.fill(draft)
                            expect(composer).to_have_value(draft)
                            expect(composer).to_have_css('font-size', '13px')
                            page.wait_for_function('''() => {
                                const el = document.getElementById('ai-widget-input');
                                return Math.abs(el.getBoundingClientRect().height - Math.max(36, Math.min(el.scrollHeight, 120))) < 2;
                            }''')
                            widget = page.locator('#ai-widget').bounding_box()
                            area = page.locator('#ai-widget .ai-input-area').bounding_box()
                            main = page.locator('#ai-widget .ai-main-chat').bounding_box()
                            self.assertAlmostEqual(area['x'] - main['x'], main['x'] + main['width'] - area['x'] - area['width'], delta=1)
                            self.assertLessEqual(area['y'] + area['height'], widget['y'] + widget['height'])
                            self.assertLessEqual(page.locator('#ai-widget').evaluate('el => el.scrollWidth - el.clientWidth'), 1)
                            if width <= 480:
                                text, photo = composer.bounding_box(), page.locator('#ai-widget-photo').bounding_box()
                                self.assertLessEqual(text['y'] + text['height'], photo['y'])
                            else:
                                text = composer.bounding_box()
                                for selector in ('#ai-widget-photo', '#ai-widget-mic', '#ai-widget-send'):
                                    control = page.locator(selector).bounding_box()
                                    self.assertAlmostEqual(text['y'] + text['height'], control['y'] + control['height'], delta=1)
                            page.screenshot(path=str(artifacts / f'ai-composer-refined-{width}-{theme}.png'), animations='disabled')

                            trigger = page.get_by_role('button', name='View generated design')
                            trigger.focus()
                            page.keyboard.press('Enter')
                            dialog = page.get_by_role('dialog', name='Design preview')
                            expect(dialog).to_be_visible()
                            expect(page.locator('[data-ai-preview-close]')).to_be_focused()
                            expect(page.locator('[data-ai-preview-image]')).to_be_visible()
                            expect(page.locator('[data-ai-preview-download]')).to_have_attribute('href', self.live_server_url + '/media/ai_generated/ui-preview.png')
                            expect(page.locator('[data-ai-preview-download]')).to_have_css('text-decoration-line', 'none')
                            bounds = dialog.bounding_box()
                            self.assertGreaterEqual(bounds['x'], 0)
                            self.assertGreaterEqual(bounds['y'], 0)
                            self.assertLessEqual(bounds['x'] + bounds['width'], width)
                            self.assertLessEqual(bounds['y'] + bounds['height'], height)
                            page.screenshot(path=str(artifacts / f'ai-preview-refined-{width}-{theme}.png'), animations='disabled')
                            if width == 320:
                                page.locator('[data-ai-preview-close]').click()
                            elif width == 600:
                                page.mouse.click(1, 1)
                            else:
                                page.keyboard.press('Escape')
                            expect(dialog).to_be_hidden()
                            expect(trigger).to_be_focused()
                            self.assertFalse(page.locator('body').evaluate('el => el.classList.contains("ai-preview-open")'))
                            self.assertEqual(posts, [])

                        page.set_viewport_size({'width': 1440, 'height': 1000})
                        page.locator('#ai-guide-open').click()
                        options = page.locator('.ai-guide-options label')
                        page.mouse.move(0, 0)
                        expect(options.first).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                        options.first.click()
                        selected = options.first.evaluate('el => getComputedStyle(el).backgroundColor')
                        self.assertNotIn(selected, ('rgb(0, 0, 0)', 'rgb(255, 255, 255)'))
                        page.locator('[name="guide_occasion"][value="other"]').check()
                        other = page.locator('#ai-guide-other')
                        other.fill('Graduation')
                        self.assertEqual(other.evaluate(field_style), expected_style)
                        page.locator('#ai-guide-next').click()
                        page.locator('#ai-guide-suggest').click()
                        page.mouse.move(0, 0)
                        expect(page.locator('.ai-guide-style-choice').first).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
                        page.locator('.ai-guide-style-choice').first.click()
                        self.assertNotIn(page.locator('.ai-guide-style-choice').first.evaluate('el => getComputedStyle(el).backgroundColor'), ('rgb(0, 0, 0)', 'rgb(255, 255, 255)'))
                        page.locator('#ai-guide-exit').click()

                        # Image failure has readable feedback, and closing remains available.
                        page.get_by_role('button', name='View generated design').click()
                        page.locator('[data-ai-preview-image]').evaluate('el => el.dispatchEvent(new Event("error"))')
                        expect(page.locator('[data-ai-preview-error]')).to_be_visible()
                        expect(page.locator('[data-ai-preview-download]')).to_be_hidden()
                        page.keyboard.press('Escape')
                        expect(page.locator('#ai-image-preview')).to_be_hidden()
                        self.assertEqual(posts, [])
                        self.assertEqual(errors, [])
                        context.close()
            finally:
                browser.close()

    def test_customer_chat_launcher_tooltips_and_hover_lift(self):
        from playwright.sync_api import expect, sync_playwright
        from io import BytesIO
        from PIL import Image

        customer = User.objects.create_user(username='chat-launcher-customer', role='customer')
        self.client.force_login(customer)
        cookie = {'name': settings.SESSION_COOKIE_NAME,
                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                  'url': self.live_server_url}
        artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.add_cookies([cookie])
                for domain in ('fonts.googleapis.com', 'fonts.gstatic.com', 'cdnjs.cloudflare.com'):
                    context.route(f'https://{domain}/**', lambda route: route.abort())
                page = context.new_page()
                page.goto(self.live_server_url + reverse('home'), wait_until='domcontentloaded')
                for theme in ('light', 'dark'):
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    for width, height in ((1440, 1000), (520, 844), (390, 844), (320, 640)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.mouse.move(0, 0)
                        expect(page.locator('#adminChatToggle')).to_have_css('transform', 'none')
                        if width <= 520:
                            ai = page.locator('#ai-fab').bounding_box()
                            support = page.locator('#adminChatToggle').bounding_box()
                            self.assertAlmostEqual(ai['y'] - support['y'] - support['height'], 8, delta=1)
                        for selector in ('#ai-fab', '#adminChatToggle'):
                            launcher = page.locator(selector)
                            page.mouse.move(0, 0)
                            page.locator('body').click(position={'x': 1, 'y': 1})
                            launcher.hover()
                            expect(launcher).to_have_css('transform', 'matrix(1, 0, 0, 1, 0, -2)')
                            page.wait_for_function('''selector => getComputedStyle(document.querySelector(selector), '::after').opacity === '1' ''', arg=selector)
                            tooltip = launcher.evaluate('''el => {
                                const box = getComputedStyle(el, '::after');
                                const arrow = getComputedStyle(el, '::before');
                                return {text: box.content, bg: box.backgroundColor, ink: box.color,
                                    arrowBg: arrow.backgroundColor, arrowOpacity: arrow.opacity,
                                    left: el.getBoundingClientRect().x - parseFloat(box.width) - 12};
                            }''')
                            self.assertIn(launcher.get_attribute('aria-label'), tooltip['text'])
                            self.assertEqual(tooltip['bg'], 'rgb(255, 255, 255)' if theme == 'light' else 'rgb(36, 36, 36)')
                            self.assertNotEqual(tooltip['bg'], tooltip['ink'])
                            self.assertEqual(tooltip['arrowBg'], tooltip['bg'])
                            self.assertEqual(tooltip['arrowOpacity'], '1')
                            self.assertGreaterEqual(tooltip['left'], 0)
                            pixels = Image.open(BytesIO(page.screenshot(path=str(artifacts / f'{selector[1:]}-tooltip-{width}-{theme}.png')))).convert('RGB')
                            join = launcher.evaluate('''el => {
                                const rect = el.getBoundingClientRect();
                                return {x: rect.x + parseFloat(getComputedStyle(el).borderLeftWidth) - 13,
                                    y: rect.y + rect.height / 2};
                            }''')
                            background = 255 if theme == 'light' else 36
                            # The pointer must cover the box border at its base, without a seam.
                            for offset in (-2, 0, 2):
                                color = pixels.getpixel((round(join['x']), round(join['y'] + offset)))
                                self.assertLessEqual(max(abs(channel - background) for channel in color), 3)
                            # Keyboard users receive the same label without hovering.
                            page.mouse.move(0, 0)
                            page.keyboard.press('Tab')
                            launcher.focus()
                            page.wait_for_function('''selector => getComputedStyle(document.querySelector(selector), '::after').opacity === '1' ''', arg=selector)
                page.emulate_media(reduced_motion='reduce')
                for selector in ('#ai-fab', '#adminChatToggle'):
                    page.locator(selector).hover()
                    expect(page.locator(selector)).to_have_css('transform', 'none')
                context.close()
            finally:
                browser.close()
