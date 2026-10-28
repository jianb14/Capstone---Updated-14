"""Real touch/mouse gestures across packages, entrance arches and welcome stands."""
import os
from pathlib import Path
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import AddOn, AdditionalOnly, Package


@skipUnless(os.environ.get('RUN_PACKAGES_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class CatalogSwipeBrowserTests(StaticLiveServerTestCase):
    def test_all_three_carousels_swipe_without_clipping_or_accidental_booking(self):
        from playwright.sync_api import expect, sync_playwright

        for number in range(5):
            Package.objects.create(name=f'Package {number + 1}', price=1000,
                features='Backdrop\nBalloons\nInstallation', is_featured=number == 0)
        for number in range(4):
            AddOn.objects.create(name=f'Entrance {number + 1}', price=500,
                solo_price=800, features='Arch\nBalloons')
            AdditionalOnly.objects.create(name=f'Stand {number + 1}', price=300, features='Sign\nBalloons')
        artifacts = Path(__file__).resolve().parent.parent / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            try:
                for mobile, width in ((True, 455), (False, 1440)):
                    context = browser.new_context(viewport={'width': width, 'height': 1000},
                        has_touch=mobile, is_mobile=mobile)
                    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    sweetalert = artifacts / 'sweetalert2.all.min.js'
                    if sweetalert.exists():
                        context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                            content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    cdp = context.new_cdp_session(page)
                    page.goto(self.live_server_url + reverse('package'), wait_until='domcontentloaded')
                    catalog_url = page.url

                    def settle(track):
                        page.wait_for_function('''selector => !document.querySelector(selector).getAnimations()
                            .some(animation => animation.playState === 'running')''', arg=track)

                    def gesture(viewport, dx, dy=0, start_link=False):
                        viewport.scroll_into_view_if_needed()
                        rect = viewport.bounding_box()
                        x = rect['x'] + rect['width'] * (0.72 if dx < 0 else 0.28)
                        y = min(850, max(150, rect['y'] + rect['height'] * .45))
                        if start_link:
                            links = viewport.locator('.package-cta')
                            for link in links.all():
                                box = link.bounding_box()
                                if box['x'] >= rect['x'] and box['x'] + box['width'] <= rect['x'] + rect['width'] + 1:
                                    link.scroll_into_view_if_needed()
                                    box = link.bounding_box()
                                    x, y = box['x'] + box['width'] * .8, box['y'] + box['height'] / 2
                                    break
                        if mobile:
                            cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
                            for step in range(1, 9):
                                cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [
                                    {'x': x + dx * step / 8, 'y': y + dy * step / 8}]})
                            cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                        else:
                            page.mouse.move(x, y)
                            page.mouse.down()
                            page.mouse.move(x + dx, y + dy, steps=12)
                            page.mouse.up()

                    for selector, track, card_selector in (
                        ('.packages-carousel', '.carousel-track', '.package-card'),
                        ('.addons-carousel', '.addons-track', '.addon-card'),
                        ('.additionals-carousel', '.additionals-track', '.addon-card'),
                    ):
                        viewport = page.locator(selector)
                        styles = viewport.evaluate('el => ({x:getComputedStyle(el).overflowX, y:getComputedStyle(el).overflowY})')
                        self.assertEqual(styles, {'x': 'clip', 'y': 'visible'})
                        initial = page.locator(track).evaluate('el => getComputedStyle(el).transform')
                        gesture(viewport, -180, start_link=True)
                        settle(track)
                        moved = page.locator(track).evaluate('el => getComputedStyle(el).transform')
                        self.assertNotEqual(initial, moved, selector)
                        self.assertEqual(page.url, catalog_url)
                        self.assertFalse(viewport.evaluate('el => el.classList.contains("is-dragging")'))
                        gesture(viewport, 180)
                        settle(track)
                        self.assertEqual(page.locator(track).evaluate('el => getComputedStyle(el).transform'), initial)

                        # Inspect the entire hovered card and the popular badge in both themes.
                        for theme in ('light', 'dark'):
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            card = viewport.locator(card_selector).filter(has=page.locator('h3')).first
                            if not mobile and selector == '.packages-carousel':
                                card = viewport.locator('.package-card.featured')
                            card.hover()
                            page.wait_for_function('''selector => [...document.querySelectorAll(selector + ' ' + '.package-card, ' + selector + ' .addon-card')]
                                .every(el => !el.getAnimations().some(animation => animation.playState === 'running'))''', arg=selector)
                            viewport.evaluate('el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 100)')
                            page.screenshot(path=str(artifacts / f'catalog-swipe-{selector[1:]}-{theme}-{width}.png'), animations='disabled')

                    if mobile:
                        viewport = page.locator('.packages-carousel')
                        viewport.scroll_into_view_if_needed()
                        before = page.locator('.carousel-track').evaluate('el => getComputedStyle(el).transform')
                        scroll = page.evaluate('scrollY')
                        gesture(viewport, 0, -160)
                        page.wait_for_function('(before) => scrollY > before', arg=scroll)
                        self.assertEqual(before, page.locator('.carousel-track').evaluate('el => getComputedStyle(el).transform'))

                    # A normal click still works once the swipe's synthetic click has passed.
                    page.wait_for_timeout(450)
                    context.route('**/booking/?*', lambda route: route.fulfill(content_type='text/html', body='<h1>Booking destination</h1>'))
                    link = page.locator('.packages-carousel .package-cta').first
                    link.click()
                    expect(page.get_by_role('heading', name='Booking destination')).to_be_visible()
                    self.assertEqual(errors, [])
                    context.close()
            finally:
                browser.close()
