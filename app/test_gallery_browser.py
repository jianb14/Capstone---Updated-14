"""Opt-in gallery regression: RUN_GALLERY_BROWSER=1 with isolated fixtures."""
import io
import os
from pathlib import Path
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from .models import GalleryCategory, GalleryImage


@skipUnless(os.environ.get('RUN_GALLERY_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class GalleryBrowserTests(StaticLiveServerTestCase):
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
                expect(page.locator('#galleryLightbox')).to_have_class('gallery-lightbox active')
                expect(page.locator('#lightboxImg')).to_have_attribute('src', source)
                expect(page.locator('#lightboxImg')).to_have_attribute('alt', caption)
                page.keyboard.press('Escape')
                expect(page.locator('#galleryLightbox')).not_to_have_class('gallery-lightbox active')
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
