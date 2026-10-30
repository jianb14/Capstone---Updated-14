"""Real touch panning and the customer's bounded, reusable color history."""
import os
from pathlib import Path
from tempfile import gettempdir
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import CanvasAsset, CanvasCategory, DesignOffer, DesignRequirement, Package, User


@skipUnless(os.environ.get('RUN_DESIGN_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class CanvasInteractionsBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        user = User.objects.create_user(username='canvas_interactions', role='customer')
        self.client.force_login(user)
        category = CanvasCategory.objects.create(name='Interaction panels')
        CanvasAsset.objects.create(category=category, label='Interaction panel', static_path='images/canvas/premium/frames/panel_wall.svg')
        package = Package.objects.create(name='Interaction package', price=4799)
        offer = DesignOffer.objects.create(kind='package', package=package, is_enabled=True)
        DesignRequirement.objects.create(offer=offer, category=category, required=True, minimum=1, maximum=2)
        self.url = self.live_server_url + reverse('design_canvas') + f'?design_offer_id={offer.pk}&fresh=1'
        self.cookie = {'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}
        self.errors = []

    def launch(self, playwright):
        executable = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        return playwright.chromium.launch(executable_path=str(executable), headless=True)

    def open_page(self, browser, width, height=844):
        context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=True, is_mobile=width <= 1024)
        context.add_cookies([self.cookie])
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        # Capture the existing mobile adapter API without adding a production debug API.
        page.add_init_script('''Object.defineProperty(window, 'setupCanvasMobileEditor', {
            configurable: true,
            set(setup) {
                Object.defineProperty(window, 'setupCanvasMobileEditor', {
                    value(api) { window.testCanvas = api.canvas; return setup(api); },
                    configurable: true
                });
            }
        });''')
        page.goto(self.url, wait_until='domcontentloaded')
        self.assertEqual(page.url.split('?')[0], self.live_server_url + reverse('design_canvas'))
        page.wait_for_function('window.testCanvas && testCanvas.getWidth() === document.getElementById("canvasDropZone").clientWidth')
        return context, page

    def touch_drag(self, session, x, y, dx, dy):
        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y, 'id': 0}]})
        for step in range(1, 6):
            session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': x + dx * step / 5, 'y': y + dy * step / 5, 'id': 0}]})
        session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})

    def test_touch_moves_paper_without_moving_objects_and_mouse_still_works(self):
        from playwright.sync_api import sync_playwright, expect

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width in (320, 390, 820, 1440):
                    context, page = self.open_page(browser, width)
                    session = context.new_cdp_session(page)
                    stage = page.locator('.upper-canvas').bounding_box()
                    x, y = stage['x'] + stage['width'] / 2, stage['y'] + stage['height'] / 2
                    initial = page.evaluate('testCanvas.viewportTransform.slice()')
                    if width == 1440:
                        page.mouse.move(x, y)
                        page.mouse.down()
                        page.mouse.move(x + 20, y + 15, steps=5)
                        page.mouse.up()
                        mouse = page.evaluate('testCanvas.viewportTransform.slice()')
                        self.assertAlmostEqual(mouse[4] - initial[4], 20, delta=1)
                        self.assertAlmostEqual(mouse[5] - initial[5], 15, delta=1)
                        initial = mouse
                    self.touch_drag(session, x, y, 40, 30)
                    moved = page.evaluate('testCanvas.viewportTransform.slice()')
                    self.assertAlmostEqual(moved[4] - initial[4], 40, delta=1, msg=str(width))
                    self.assertAlmostEqual(moved[5] - initial[5], 30, delta=1, msg=str(width))
                    self.assertTrue(page.evaluate('testCanvas.selection'))
                    # A second gesture must also work, including movement in reverse.
                    self.touch_drag(session, x, y, -25, -20)
                    moved_again = page.evaluate('testCanvas.viewportTransform.slice()')
                    self.assertAlmostEqual(moved_again[4] - moved[4], -25, delta=1)
                    self.assertAlmostEqual(moved_again[5] - moved[5], -20, delta=1)
                    # Use the item's move handle, which remains usable for small text.
                    page.locator('[data-panel-target="textPanel"]').tap()
                    page.locator('.text-preset-card[title="Add a Heading"]').tap()
                    expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                    page.wait_for_function('testCanvas.getActiveObject() && !testCanvas.getActiveObject().isEditing')
                    point = page.evaluate('''() => {
                        const object = testCanvas.getActiveObject();
                        const point = object.oCoords.moveCtl;
                        const rect = testCanvas.upperCanvasEl.getBoundingClientRect();
                        return {x: rect.x + point.x, y: rect.y + point.y, left: object.left,
                            top: object.top, zoom: testCanvas.getZoom(), viewport: testCanvas.viewportTransform.slice()};
                    }''')
                    self.touch_drag(session, point['x'], point['y'], 24, 18)
                    position = page.evaluate('({left: testCanvas.getActiveObject().left, top: testCanvas.getActiveObject().top, viewport: testCanvas.viewportTransform.slice()})')
                    self.assertAlmostEqual(position['left'] - point['left'], 24 / point['zoom'], delta=2)
                    self.assertAlmostEqual(position['top'] - point['top'], 18 / point['zoom'], delta=2)
                    self.assertEqual(position['viewport'], point['viewport'])
                    context.close()
                self.assertFalse(self.errors, self.errors)
            finally:
                browser.close()

    def test_recent_colors_limit_reuse_commit_and_reload_on_mobile_and_desktop(self):
        from playwright.sync_api import sync_playwright, expect

        colors = ['#123456', '#234567', '#345678', '#456789', '#56789a', '#6789ab', '#789abc', '#89abcd', '#9abcde']
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width, theme in ((320, 'dark'), (390, 'light'), (1440, 'dark'), (1440, 'light')):
                    context, page = self.open_page(browser, width)
                    mobile = width <= 1024
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    expect(page.locator('[data-recent-colors="canvas"]')).to_have_count(0)
                    page.locator('[data-panel-target="textPanel"]').tap()
                    page.locator('.text-preset-card[title="Add a Heading"]').tap()
                    if mobile:
                        page.locator('#mobileEditItemBtn').tap()
                        page.locator('[data-edit-section="adjust"]').tap()
                        page.locator('#mobileMoreColors summary').tap()
                    else:
                        page.locator('[data-panel-target="elementsPanel"]').tap()
                    expect(page.locator('[data-recent-colors="object"]')).to_be_hidden()
                    for color in colors:
                        page.locator('#customObjectColor').fill(color)
                    expected = list(reversed(colors[1:]))
                    palette = page.locator('[data-recent-colors="object"] button')
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    expect(palette).to_have_count(8)
                    # Reusing an existing color promotes it without adding a duplicate.
                    reused = colors[3]
                    page.locator(f'[data-recent-colors="object"] button[data-color="{reused}"]').tap()
                    expected = [reused] + [color for color in expected if color != reused]
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    self.assertEqual(page.evaluate('testCanvas.getActiveObject().fill'), reused)
                    self.assertLessEqual(palette.first.evaluate('(el) => el.parentElement.scrollWidth - el.parentElement.clientWidth'), 1)
                    if mobile:
                        self.assertGreaterEqual(palette.first.bounding_box()['width'], 44)
                    # Input events must show custom colors immediately, before change.
                    # Repeated previews of one pick replace the same history slot.
                    page.locator('#customObjectColor').evaluate('''el => {
                        for (const color of ['#111122', '#222233', '#333344']) {
                            el.value = color; el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    }''')
                    expected = ['#333344'] + expected[:7]
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    self.assertEqual(page.evaluate('testCanvas.getActiveObject().fill'), '#333344')
                    page.locator('#customObjectColor').dispatch_event('change')
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    page.locator('#itemColorPicker').evaluate('''el => {
                        el.value = '#abcdef'; el.dispatchEvent(new Event('input', {bubbles: true}));
                    }''')
                    expected = ['#abcdef'] + expected[:7]
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    page.locator('#itemColorPicker').dispatch_event('change')
                    expect(palette).to_have_count(8)
                    self.assertEqual(page.evaluate('testCanvas.getActiveObject().fill'), '#abcdef')
                    page.locator('[data-recent-colors="object"]').screenshot(path=str(Path(gettempdir()) / f'balloorina-object-recent-{theme}-{width}.png'), animations='disabled')
                    # Canvas presets and custom background colors never enter this history.
                    if mobile:
                        page.locator('#mobileEditItemDialog [data-mobile-close]').tap()
                        page.locator('#mobileCanvasToolsBtn').tap()
                        page.locator('#mobileCanvasToolsDialog details').first.locator('summary').tap()
                    page.locator('.color-swatch[data-target="canvas"][data-color="#000000"]').tap()
                    page.locator('#customCanvasColor').fill('#fedcba')
                    self.assertEqual(page.evaluate('testCanvas.getObjects().find(object => object._isArtboard).fill'), '#fedcba')
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    page.reload(wait_until='domcontentloaded')
                    page.wait_for_function('window.testCanvas')
                    self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), expected)
                    expect(page.locator('[data-recent-colors="canvas"]')).to_have_count(0)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                    context.close()
                self.assertFalse(self.errors, self.errors)
            finally:
                browser.close()

    def test_custom_object_color_is_saved_without_a_selection_or_change_event(self):
        from playwright.sync_api import sync_playwright, expect

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context, page = self.open_page(browser, 1440)
                # Old mixed histories must not import background colors into Object Color.
                page.evaluate('''() => localStorage.setItem(
                    `designCanvasRecentColors:v1:user-${window.canvasUserId}`, JSON.stringify(['#fedcba']))''')
                page.reload(wait_until='domcontentloaded')
                page.wait_for_function('window.testCanvas')
                page.locator('[data-panel-target="elementsPanel"]').tap()
                group = page.locator('[data-recent-colors="object"]')
                palette = group.locator('button')
                expect(group).to_be_hidden()
                page.locator('#customObjectColor').evaluate('''el => {
                    el.value = '#13579b'; el.dispatchEvent(new Event('input', {bubbles: true}));
                }''')
                expect(group).to_be_visible()
                expect(palette).to_have_count(1)
                expect(palette.first).to_have_attribute('data-color', '#13579b')
                self.assertEqual(page.evaluate('testCanvas.getObjects().filter(object => !object._isArtboard).length'), 0)
                self.assertEqual(page.evaluate('testCanvas.getObjects().find(object => object._isArtboard).fill'), '#ffffff')
                # Reopening or leaving a picker must keep separate custom picks,
                # even when a browser sends no change event between them.
                for event, color in (('click', '#2468ac'), ('blur', '#3579bd'), ('keydown', '#468ace')):
                    page.locator('#customObjectColor').dispatch_event(event, {'key': 'Enter'} if event == 'keydown' else {})
                    page.locator('#customObjectColor').evaluate('''(el, color) => {
                        el.value = color; el.dispatchEvent(new Event('input', {bubbles: true}));
                    }''', color)
                expect(palette).to_have_count(4)
                self.assertEqual(palette.evaluate_all('(buttons) => buttons.map(button => button.dataset.color)'), ['#468ace', '#3579bd', '#2468ac', '#13579b'])
                page.locator('#customObjectColor').dispatch_event('change')
                page.locator('[data-panel-target="textPanel"]').tap()
                page.locator('.text-preset-card[title="Add a Heading"]').tap()
                page.locator('[data-panel-target="elementsPanel"]').tap()
                page.locator('[data-recent-colors="object"] button[data-color="#13579b"]').tap()
                self.assertEqual(page.evaluate('testCanvas.getActiveObject().fill'), '#13579b')
                # A locked object cannot apply or add another color to the history.
                page.evaluate('testCanvas.getActiveObject()._isLocked = true')
                page.locator('#customObjectColor').evaluate('''el => {
                    el.value = '#987654'; el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }''')
                expect(palette).to_have_count(4)
                expect(palette.first).to_have_attribute('data-color', '#13579b')
                self.assertEqual(page.evaluate('testCanvas.getActiveObject().fill'), '#13579b')
                self.assertFalse(self.errors, self.errors)
                context.close()
            finally:
                browser.close()

    def test_requested_font_menu_loads_real_faces_and_keeps_missing_fonts_unavailable(self):
        import time
        from playwright.sync_api import sync_playwright, expect

        expected = ['Poppins', 'Montserrat', 'Cursive Sans', 'Cursive Serif', 'Bebas Neue',
                    'Liberation Sans', 'Histore Magica', 'Angelic Pearl', 'Megalona', 'Day Roman',
                    'Sanchez', 'Ananda', 'Jane Austen', 'Michland', 'Golden Hills', 'Impact',
                    'Steelfish', 'Bebas Kai']
        bundled = ['Poppins', 'Montserrat', 'Cursive Sans', 'Cursive Serif', 'Bebas Neue',
                   'Liberation Sans', 'Day Roman', 'Sanchez', 'Bebas Kai']
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width in (320, 1440):
                    context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=True, is_mobile=width == 320)
                    context.add_cookies([self.cookie])
                    # The canvas typefaces must work from the bundled files.
                    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                    if width == 320:
                        def slow_font(route):
                            # Slow connections must not permanently disable a real font.
                            time.sleep(5.5)
                            route.fulfill(path=str(Path(settings.BASE_DIR) / 'static/fonts/canvas/liberation-sans/regular.woff2'), content_type='font/woff2')
                        context.route('**/fonts/canvas/liberation-sans/regular.woff2', slow_font)
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda error: self.errors.append(str(error)))
                    page.add_init_script('''Object.defineProperty(window, 'setupCanvasMobileEditor', {
                        configurable: true, set(setup) {
                            Object.defineProperty(window, 'setupCanvasMobileEditor', {
                                value(api) { window.testCanvas = api.canvas; return setup(api); }, configurable: true
                            });
                        }
                    });''')
                    page.goto(self.url, wait_until='domcontentloaded')
                    page.wait_for_function('''() => window.testCanvas &&
                        [...document.querySelector('#fontFamilySelect').options]
                            .filter(option => option.value).every(option => option.dataset.fontAvailable)''')
                    values = page.locator('#fontFamilySelect option').evaluate_all('(options) => options.map(option => option.value).filter(Boolean)')
                    self.assertEqual(values, expected)
                    page.locator('[data-panel-target="textPanel"]').tap()
                    page.locator('.text-preset-card[title="Add a Heading"]').tap()
                    if width == 320:
                        page.locator('#mobileEditItemBtn').tap()
                    for font in bundled:
                        self.assertFalse(page.locator(f'#fontFamilySelect option[value="{font}"]').is_disabled(), font)
                        page.locator('#fontFamilyDropdown .dropdown-trigger').tap()
                        page.locator(f'#fontFamilyOptions li[data-value="{font}"]').tap()
                        page.wait_for_function('(font) => testCanvas.getActiveObject().fontFamily === font', arg=font)
                        self.assertTrue(page.evaluate('''async font => {
                            const faces = await document.fonts.load(`bold 42px "${font}"`);
                            return faces.length > 0 && faces.every(face => face.status === 'loaded');
                        }''', font))
                        self.assertGreater(page.evaluate('testCanvas.getActiveObject().width'), 0)
                    # An unavailable face cannot be applied as a differently rendered fallback.
                    expect(page.locator('#fontFamilySelect option[value="Histore Magica"]')).to_be_disabled()
                    expect(page.locator('#fontFamilyOptions li[data-value="Histore Magica"]')).to_have_attribute('aria-disabled', 'true')
                    page.locator('#fontFamilySelect').evaluate('''el => {
                        el.value = 'Histore Magica'; el.dispatchEvent(new Event('change', {bubbles: true}));
                    }''')
                    expect(page.locator('#fontFamilySelect')).to_have_value('Bebas Kai')
                    self.assertEqual(page.evaluate('testCanvas.getActiveObject().fontFamily'), 'Bebas Kai')
                    # Saved older lettering stays intact without reintroducing its menu entry.
                    page.evaluate('''() => {
                        const object = testCanvas.getActiveObject(); object.set('fontFamily', 'Oswald');
                        testCanvas.fire('selection:updated', {selected: [object]});
                    }''')
                    self.assertEqual(page.locator('#fontFamilySelect option').evaluate_all('(options) => options.map(option => option.value).filter(Boolean)'), expected)
                    page.locator('#fontFamilyDropdown .dropdown-trigger').tap()
                    page.screenshot(path=str(Path(gettempdir()) / f'balloorina-font-menu-{width}.png'), animations='disabled')
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth - innerWidth'), 1)
                    context.close()
                self.assertFalse(self.errors, self.errors)
            finally:
                browser.close()
