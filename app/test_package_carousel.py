"""Natural package order and precise carousel alignment across screen sizes."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Package


def seed_packages():
    return {name: Package.objects.create(name=name, price=1000, features='Backdrop\nBalloons')
            for name in ('Package 3', 'Package 1-B', 'Package 10', 'Package 1-A', 'Package 2')}


class PackageOrderTests(TestCase):
    def setUp(self):
        self.packages = seed_packages()

    def names(self):
        names = [package.name for package in self.client.get(reverse('package')).context['packages']]
        self.assertEqual(names, [package.name for package in self.client.get('/package/').context['packages']])
        return names

    def test_numeric_name_order_does_not_follow_creation_order(self):
        self.assertEqual(self.names(), ['Package 1-A', 'Package 1-B', 'Package 2', 'Package 3', 'Package 10'])

    def test_popular_packages_group_together_and_keep_natural_order(self):
        Package.objects.filter(name__in=['Package 3', 'Package 1-B']).update(is_featured=True)
        self.assertEqual(self.names(), ['Package 1-B', 'Package 3', 'Package 1-A', 'Package 2', 'Package 10'])

    def test_single_popular_package_keeps_remaining_packages_in_order(self):
        Package.objects.filter(name='Package 2').update(is_featured=True)
        self.assertEqual(self.names(), ['Package 2', 'Package 1-A', 'Package 1-B', 'Package 3', 'Package 10'])


@skipUnless(os.environ.get('RUN_PACKAGES_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, REQUEST_RATE_LIMITING_ENABLED=False)
class PackageCarouselBrowserTests(StaticLiveServerTestCase):
    def test_responsive_popular_badge_stays_inside_clip_area_including_hover(self):
        from playwright.sync_api import sync_playwright

        seed_packages()
        Package.objects.filter(name='Package 1-A').update(is_featured=True)
        artifacts = Path(__file__).resolve().parent.parent / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            page = browser.new_page(viewport={'width': 455, 'height': 1000})
            page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                page.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            try:
                page.goto(self.live_server_url + reverse('package'), wait_until='domcontentloaded')
                page.add_style_tag(content='.carousel-track, .package-card, .carousel-btn { transition: none !important; }')
                for theme in ('light', 'dark'):
                    for width in (1024, 900, 768, 455, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.evaluate('(theme) => { document.documentElement.dataset.theme = theme; window.dispatchEvent(new Event("resize")); }', theme)
                        card = page.locator('.package-card.featured')
                        card.hover()
                        bounds = card.locator('.package-badge').evaluate('''el => {
                            const badge = el.getBoundingClientRect();
                            const viewport = el.closest('.packages-carousel').getBoundingClientRect();
                            return {top:badge.top - viewport.top, left:badge.left - viewport.left,
                                right:viewport.right - badge.right};
                        }''')
                        self.assertGreaterEqual(bounds['top'], 6, f'{theme}, width={width}, {bounds}')
                        self.assertGreaterEqual(bounds['left'], 0)
                        self.assertGreaterEqual(bounds['right'], 0)
                        if width <= 768:
                            page.get_by_role('button', name='Next packages', exact=True).click()
                            page.get_by_role('button', name='Previous packages', exact=True).click()
                            card.hover()
                            self.assertGreaterEqual(card.locator('.package-badge').evaluate(
                                'el => el.getBoundingClientRect().top - el.closest(".packages-carousel").getBoundingClientRect().top'), 6)
                        page.locator('.packages-carousel').evaluate('el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 100)')
                        page.screenshot(path=str(artifacts / f'package-badge-{theme}-{width}.png'), animations='disabled')
            finally:
                browser.close()

    def test_popular_positions_natural_successors_and_fractional_alignment(self):
        from playwright.sync_api import expect, sync_playwright

        seed_packages()
        artifacts = Path(__file__).resolve().parent.parent / '.booking-followup-check'
        artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1100})
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            sweetalert = artifacts / 'sweetalert2.all.min.js'
            if sweetalert.exists():
                context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11', lambda route: route.fulfill(
                    content_type='application/javascript', body=sweetalert.read_text(encoding='utf-8')))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def settle():
                page.wait_for_function('''() => !document.querySelector('.carousel-track').getAnimations()
                    .some(animation => animation.playState === 'running')''')

            def shown():
                return page.locator('.packages-carousel').evaluate('''el => {
                    const rect = el.getBoundingClientRect();
                    return [...el.querySelectorAll('.package-card')]
                        .filter(card => {const r = card.getBoundingClientRect(); return r.left >= rect.left - .1 && r.right <= rect.right + .1;})
                        .map(card => card.querySelector('h3').textContent);
                }''')

            def set_featured(names):
                Package.objects.update(is_featured=False)
                Package.objects.filter(name__in=names).update(is_featured=True)

            try:
                cases = (
                    ([], ['Package 1-A', 'Package 1-B', 'Package 2']),
                    (['Package 1-A'], ['Package 10', 'Package 1-A', 'Package 1-B']),
                    (['Package 2'], ['Package 1-B', 'Package 2', 'Package 3']),
                    (['Package 1-A', 'Package 1-B'], ['Package 1-A', 'Package 1-B', 'Package 2']),
                    (['Package 1-A', 'Package 1-B', 'Package 2'], ['Package 1-A', 'Package 1-B', 'Package 2']),
                )
                for featured, initial in cases:
                    with ThreadPoolExecutor(max_workers=1) as worker:
                        worker.submit(set_featured, featured).result()
                    page.set_viewport_size({'width': 1440, 'height': 1100})
                    page.goto(self.live_server_url + reverse('package'), wait_until='domcontentloaded')
                    self.assertEqual(shown(), initial)
                    if len(featured) == 1:
                        page.get_by_role('button', name='Next packages', exact=True).click()
                        settle()
                        natural = ['Package 1-A', 'Package 1-B', 'Package 2', 'Package 3', 'Package 10']
                        start = natural.index(featured[0])
                        self.assertEqual(shown(), (natural[start:] + natural[:start])[:3])
                        for theme in ('light', 'dark'):
                            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                            page.locator('.packages-carousel').scroll_into_view_if_needed()
                            page.screenshot(path=str(artifacts / f'package-carousel-border-{theme}.png'), animations='disabled')
                    # The animated navigation above covers the transition. Measure
                    # the larger resize matrix without waiting half a second per click.
                    page.add_style_tag(content='.carousel-track { transition-duration: 0s !important; }')
                    for width in (1440, 1366, 1101, 1024, 900, 768, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 1100})
                        page.evaluate('window.dispatchEvent(new Event("resize"))')
                        page.wait_for_function('''() => {
                            const el = document.querySelector('.packages-carousel');
                            return Math.abs(el.querySelector('.package-card').getBoundingClientRect().left
                                - el.getBoundingClientRect().left - parseFloat(getComputedStyle(el).paddingLeft)) < .05;
                        }''')
                        if width <= 768 and featured:
                            self.assertEqual(shown(), [featured[0]])
                        for _ in range(4):
                            page.get_by_role('button', name='Next packages', exact=True).click()
                            settle()
                            error = page.locator('.packages-carousel').evaluate('''el => {
                                const viewport = el.getBoundingClientRect();
                                const expected = viewport.left + parseFloat(getComputedStyle(el).paddingLeft);
                                const cards = [...el.querySelectorAll('.package-card')];
                                return Math.min(...cards.map(card => Math.abs(card.getBoundingClientRect().left - expected)));
                            }''')
                            self.assertLess(error, .05, f'{featured}, width={width}')
                        page.get_by_role('button', name='Previous packages', exact=True).click()
                        settle()
                    expect(page.locator('.package-card.featured')).to_have_count(len(featured))
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
