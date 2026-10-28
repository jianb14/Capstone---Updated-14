"""Opt-in gallery regression: RUN_GALLERY_BROWSER=1 with isolated fixtures."""
import io
import os
from pathlib import Path
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from .models import GalleryCategory, GalleryImage, User


@skipUnless(os.environ.get('RUN_GALLERY_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class GalleryBrowserTests(StaticLiveServerTestCase):
    def test_admin_caption_counter_and_inline_validation_before_saving(self):
        from django.conf import settings
        from playwright.sync_api import expect, sync_playwright

        admin = User.objects.create_user(username='caption-browser-admin', role='admin', email_verified=True)
        category = GalleryCategory.objects.create(name='Birthday')
        image = GalleryImage.objects.create(category=category, image='gallery/browser-caption.png', caption='Existing caption')
        self.client.force_login(admin)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = Path(__file__).resolve().parent.parent / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        output = io.BytesIO()
        Image.new('RGB', (480, 640), '#8b7662').save(output, 'PNG')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            context.route('**/media/gallery/**', lambda route: route.fulfill(content_type='image/png', body=output.getvalue()))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                url = self.live_server_url + reverse('admin_gallery_image_edit', args=[image.pk])
                page.goto(url, wait_until='domcontentloaded')
                caption = page.locator('#caption')
                expect(caption).to_have_value('Existing caption')
                expect(caption).to_have_attribute('maxlength', '255')
                expect(page.locator('#imageFileNameText')).to_have_text('browser-caption.png')
                caption.evaluate('el => { el.value = "x".repeat(256); el.dispatchEvent(new Event("input", {bubbles:true})); }')
                expect(page.locator('#captionCount')).to_have_text('256')
                page.get_by_role('button', name='Update', exact=True).click()
                expect(page.locator('#captionError')).to_have_text('Use 255 characters or fewer for the caption.')
                expect(caption).to_be_focused()
                for theme in ('light', 'dark'):
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        caption.scroll_into_view_if_needed()
                        self.assertFalse(caption.evaluate('el => el.offsetWidth > el.parentElement.clientWidth + 1'))
                        page.screenshot(path=str(artifacts / f'gallery-caption-admin-{theme}-{width}.png'), animations='disabled')
                caption.fill('A new caption')
                expect(page.locator('#captionError')).to_be_hidden()
                expect(page.locator('#captionCount')).to_have_text('13')
                page.get_by_role('button', name='Update', exact=True).click()
                page.wait_for_url(self.live_server_url + reverse('admin_gallery'))
                page.goto(url, wait_until='domcontentloaded')
                expect(caption).to_have_value('A new caption')
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()

    def test_masonry_natural_ratios_animation_lazy_loading_filters_and_lightbox(self):
        from playwright.sync_api import expect, sync_playwright

        birthday = GalleryCategory.objects.create(name='Birthday')
        corporate = GalleryCategory.objects.create(name='Corporate')
        GalleryCategory.objects.create(name='Empty category')
        GalleryImage.objects.bulk_create([
            GalleryImage(category=birthday if i % 2 else corporate,
                image=f'gallery/browser-{i}.png', caption=f'Event {i}')
            for i in range(120)
        ])
        GalleryImage.objects.create(category=birthday, image='gallery/hidden.png',
            caption='Hidden event', is_active=False)
        image_bytes = []
        for size in ((480, 640), (640, 480), (480, 480)):
            output = io.BytesIO()
            Image.new('RGB', size, '#8b7662').save(output, format='PNG')
            image_bytes.append(output.getvalue())
        artifacts = Path(__file__).resolve().parent.parent / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            requests = []

            def serve_image(route):
                import re
                requests.append(route.request.url)
                number = int(re.search(r'(?:image/|browser-)(\d+)', route.request.url).group(1))
                route.fulfill(content_type='image/png', body=image_bytes[number % 3])

            context.route('**/media/gallery/**', serve_image)
            context.route('**/gallery/image/*/preview/**', serve_image)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + reverse('gallery'), wait_until='networkidle')
                items = page.locator('.gallery-grid .gallery-item')
                expect(items).to_have_count(120)
                self.assertGreaterEqual(len(requests), 4)
                self.assertLess(len(requests), 120, 'Offscreen images should remain lazy-loaded')
                self.assertEqual(items.locator('img[loading="eager"]').count(), 4)
                self.assertEqual(items.locator('img[loading="lazy"]').count(), 116)
                expect(page.locator('.gallery-grid.masonry-ready.gallery-animated')).to_be_visible()
                self.assertFalse(items.last.evaluate('el => el.classList.contains("show")'))

                # Filtering must settle synchronously, even after repeated fast switches.
                result = page.evaluate('''() => {
                    const buttons = [...document.querySelectorAll('#gallery .filter-btn')];
                    for (let i = 0; i < 20; i++) buttons[i % 2 ? 0 : 1].click();
                    buttons.find(b => b.textContent === 'Birthday').click();
                    const visible = [...document.querySelectorAll('.gallery-grid .gallery-item:not([hidden])')];
                    return {count: visible.length, categories: [...new Set(visible.map(el => el.dataset.category))],
                        immediate: visible.every(el => getComputedStyle(el).display !== 'none')};
                }''')
                self.assertEqual(result, {'count': 60, 'categories': [str(birthday.pk)], 'immediate': True})
                expect(page.get_by_role('button', name='Birthday', exact=True)).to_have_attribute('aria-pressed', 'true')
                page.wait_for_function('''() => [...document.querySelectorAll('.gallery-item:not([hidden])')].slice(0,4)
                    .every(el => getComputedStyle(el).opacity === '1')''')
                self.assertTrue(page.locator('.gallery-item:not([hidden])').evaluate_all('''els => els.every(el =>
                    parseFloat(getComputedStyle(el).transitionDelay) <= 0.165)'''))
                page.emulate_media(reduced_motion='reduce')

                for theme in ('light', 'dark'):
                    for width, columns in ((1440, 4), (900, 3), (700, 2), (390, 2), (320, 2)):
                        page.set_viewport_size({'width': width, 'height': 1000 if width > 700 else 844})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        visible = page.locator('.gallery-item:not([hidden])')
                        page.wait_for_function('''() => {
                            const items = [...document.querySelectorAll('.gallery-item:not([hidden])')];
                            return items.slice(0,4).every(el => Math.abs(parseFloat(el.style.gridRowEnd.replace('span ', ''))
                                - el.offsetHeight - parseFloat(getComputedStyle(el.parentElement).getPropertyValue('--gallery-gap'))) <= 1);
                        }''')
                        positions = visible.evaluate_all('els => els.slice(0, 5).map(el => { const r = el.getBoundingClientRect(); return {x:r.x, y:r.y}; })')
                        for i in range(1, columns):
                            self.assertAlmostEqual(positions[0]['y'], positions[i]['y'], delta=1)
                            self.assertGreater(positions[i]['x'], positions[i - 1]['x'])
                        self.assertGreater(positions[columns]['y'], positions[0]['y'])
                        dimensions = visible.evaluate_all('els => els.slice(0,4).map(el => { const img = el.querySelector("img"); return {height:img.offsetHeight, width:img.offsetWidth, ratio:img.naturalHeight/img.naturalWidth}; })')
                        self.assertGreater(len({round(item['height']) for item in dimensions}), 1)
                        for item in dimensions:
                            self.assertAlmostEqual(item['height'], item['width'] * item['ratio'], delta=1)
                        self.assertFalse(page.locator('.gallery-grid').evaluate('el => el.scrollWidth > el.clientWidth + 1'))
                        visible.first.scroll_into_view_if_needed()
                        page.screenshot(path=str(artifacts / f'gallery-{theme}-{width}.png'), animations='disabled')

                first = page.locator('.gallery-item:not([hidden])').first
                source = first.locator('img').get_attribute('data-full-image')
                caption = first.locator('img').get_attribute('alt')
                first.click()
                dialog = page.locator('#galleryLightbox')
                expect(dialog).to_be_visible()
                expect(page.locator('#lightboxImg')).to_have_attribute('src', source)
                expect(page.locator('#lightboxImg')).to_have_attribute('alt', caption)
                expect(page.get_by_role('button', name='Close image preview')).to_be_focused()
                expect(page.locator('#lightboxCaption')).to_have_text(caption)
                page.keyboard.press('Escape')
                expect(dialog).not_to_be_visible()
                expect(first).to_be_focused()

                long_caption = ('A celebration with carefully styled balloons and custom details.\n' * 25
                    + 'unbrokendescription' * 35 + '\n<b>Caption stays plain text</b>')
                first.locator('.gallery-caption').evaluate('(el, text) => el.textContent = text', long_caption)
                for theme in ('light', 'dark'):
                    for width, height in ((1440, 1000), (390, 844), (320, 568), (640, 360)):
                        page.set_viewport_size({'width': width, 'height': height})
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        first.focus()
                        page.keyboard.press('Enter')
                        expect(dialog).to_be_visible()
                        expect(page.locator('#lightboxCaption')).to_have_text(long_caption)
                        self.assertEqual(page.locator('#lightboxCaption > *').count(), 0)
                        page.wait_for_function('document.getElementById("lightboxImg").naturalWidth > 0')
                        geometry = dialog.evaluate('''el => {
                            const box = node => { const r = node.getBoundingClientRect();
                                return {x:r.x, y:r.y, right:r.right, bottom:r.bottom, width:r.width, height:r.height}; };
                            const image = el.querySelector('#lightboxImg');
                            const details = el.querySelector('#lightboxDetails');
                            return {dialog:box(el), close:box(el.querySelector('#lightboxClose')),
                                image:box(image), pane:box(el.querySelector('.gallery-viewer__image')),
                                details:box(details), ratio:image.naturalHeight / image.naturalWidth,
                                horizontalOverflow:details.scrollWidth > details.clientWidth + 1,
                                verticalScroll:details.scrollHeight > details.clientHeight};
                        }''')
                        self.assertGreaterEqual(geometry['dialog']['x'], 0)
                        self.assertGreaterEqual(geometry['dialog']['y'], 0)
                        self.assertLessEqual(geometry['dialog']['right'], width)
                        self.assertLessEqual(geometry['dialog']['bottom'], height)
                        self.assertLessEqual(geometry['close']['bottom'], geometry['dialog']['bottom'])
                        self.assertGreaterEqual(geometry['close']['y'], geometry['dialog']['y'])
                        self.assertFalse(geometry['horizontalOverflow'])
                        self.assertTrue(geometry['verticalScroll'])
                        self.assertLessEqual(geometry['image']['right'], geometry['pane']['right'] + 1)
                        self.assertLessEqual(geometry['image']['bottom'], geometry['pane']['bottom'] + 1)
                        self.assertGreaterEqual(geometry['image']['y'], geometry['pane']['y'] - 1)
                        self.assertAlmostEqual(geometry['image']['height'], geometry['image']['width'] * geometry['ratio'], delta=1)
                        if width <= 760:
                            self.assertGreaterEqual(geometry['details']['y'], geometry['pane']['bottom'] - 1)
                        else:
                            self.assertGreaterEqual(geometry['details']['x'], geometry['pane']['right'] - 1)
                        page.screenshot(path=str(artifacts / f'gallery-viewer-{theme}-{width}.png'), animations='disabled')
                        page.get_by_role('button', name='Close image preview').click()
                        expect(dialog).not_to_be_visible()
                        expect(first).to_be_focused()

                first.locator('.gallery-caption').evaluate('el => el.textContent = ""')
                page.keyboard.press('Space')
                expect(dialog).to_be_visible()
                expect(page.locator('#lightboxDetails')).to_be_hidden()
                expect(page.locator('#lightboxCaption')).to_have_text('')
                self.assertEqual(page.locator('#lightboxBody.has-caption').count(), 0)
                page.mouse.click(1, 1)
                expect(dialog).not_to_be_visible()
                self.assertEqual(page.evaluate('document.body.style.overflow'), '')
                page.get_by_role('button', name='Empty category', exact=True).click()
                expect(page.locator('.gallery-item:visible')).to_have_count(0)
                expect(page.locator('#galleryEmpty')).to_be_visible()
                page.get_by_role('button', name='All Projects', exact=True).click()
                expect(page.locator('.gallery-item:visible')).to_have_count(120)
                expect(page.locator('#galleryEmpty')).to_be_hidden()
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
