"""Real touch navigation and the customer's bounded, reusable color history."""
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

    def pinch(self, session, x, y, start_distance, end_distance, dx=0, dy=0, sequential=False):
        def points(distance, fraction=0):
            return [{'x': x + dx * fraction + offset * distance / 2,
                     'y': y + dy * fraction, 'id': identifier}
                    for identifier, offset in ((0, -1), (1, 1))]

        initial = points(start_distance)
        if sequential:
            session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': initial[:1]})
        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': initial})
        for step in range(1, 7):
            fraction = step / 6
            session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': points(
                start_distance + (end_distance - start_distance) * fraction, fraction)})
        session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})

    def test_mobile_view_stays_panned_when_adding_selecting_and_editing_images(self):
        from io import BytesIO
        from PIL import Image
        from playwright.sync_api import sync_playwright, expect

        photo = BytesIO()
        Image.new('RGB', (120, 90), '#7ba8bd').save(photo, format='PNG')

        def settle(page):
            page.wait_for_function('''testCanvas.getWidth() === document.getElementById('canvasDropZone').clientWidth &&
                testCanvas.getHeight() === document.getElementById('canvasDropZone').clientHeight''')
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')

        def view(page):
            return page.evaluate('''() => {
                const paper = testCanvas.getObjects().find(object => object._isArtboard);
                return {viewport: testCanvas.viewportTransform.slice(),
                        paper: {left: paper.left, top: paper.top, width: paper.width, height: paper.height}};
            }''')

        def tap_selected_image_again(page):
            page.locator('#mobileDeselectBtn').tap()
            settle(page)
            point = page.evaluate('''() => {
                const image = testCanvas.getObjects().filter(object => !object._isArtboard).at(-1);
                const point = fabric.util.transformPoint(image.getCenterPoint(), testCanvas.viewportTransform);
                const rect = testCanvas.upperCanvasEl.getBoundingClientRect();
                return {x: rect.left + point.x, y: rect.top + point.y};
            }''')
            page.evaluate('''() => {
                window.selectionFrameSamples = [];
                const sample = () => {
                    const paper = testCanvas.getObjects().find(object => object._isArtboard);
                    const point = fabric.util.transformPoint(paper.getCenterPoint(), testCanvas.viewportTransform);
                    const scale = testCanvas.getRetinaScaling();
                    const alpha = testCanvas.contextContainer.getImageData(
                        Math.floor(point.x * scale), Math.floor(point.y * scale), 1, 1).data[3];
                    selectionFrameSamples.push({alpha, width: testCanvas.getWidth(), height: testCanvas.getHeight()});
                    window.selectionFrameRequest = requestAnimationFrame(sample);
                };
                window.selectionFrameRequest = requestAnimationFrame(sample);
            }''')
            page.touchscreen.tap(point['x'], point['y'])
            expect(page.locator('#mobileSelectionBar')).to_be_visible()
            settle(page)
            frames = page.evaluate('''() => {
                cancelAnimationFrame(window.selectionFrameRequest);
                return selectionFrameSamples;
            }''')
            self.assertTrue(frames, 'The image selection must include rendered frames')
            self.assertTrue(all(frame['alpha'] == 255 for frame in frames),
                            f'The paper blinked during image selection: {frames}')

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width, height in ((320, 740), (390, 844), (820, 1000)):
                    with self.subTest(width=width):
                        context, page = self.open_page(browser, width, height)
                        session = context.new_cdp_session(page)
                        stage = page.locator('.upper-canvas').bounding_box()
                        x, y = stage['x'] + stage['width'] / 2, stage['y'] + stage['height'] / 2
                        self.touch_drag(session, x, y, 35, 25)
                        self.pinch(session, x, y, 60, 90)
                        expected_view = view(page)
                        page.locator('[data-panel-target="elementsPanel"]').tap()
                        page.locator('.draggable-item[title="Interaction panel"]').tap()
                        expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                        expect(page.locator('#mobileSelectionBar')).to_be_visible()
                        settle(page)
                        self.assertEqual(view(page), expected_view, 'Adding a catalog image reset the view')
                        tap_selected_image_again(page)
                        self.assertEqual(view(page), expected_view, 'Tapping a catalog image reset the view')
                        page.locator('#mobileDeselectBtn').tap()
                        settle(page)
                        self.assertEqual(view(page), expected_view, 'Deselecting reset the view')
                        page.locator('[data-panel-target="uploadsPanel"]').tap()
                        page.locator('#userUploadInput').set_input_files({
                            'name': 'mobile-reference.png', 'mimeType': 'image/png', 'buffer': photo.getvalue()})
                        page.locator('#userUploadsGrid .draggable-item').first.tap()
                        expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                        settle(page)
                        self.assertEqual(view(page), expected_view, 'Adding an uploaded photo reset the view')
                        tap_selected_image_again(page)
                        self.assertEqual(view(page), expected_view, 'Tapping an uploaded photo reset the view')
                        objects = page.evaluate('testCanvas.getObjects().map(object => object.toObject())')
                        page.locator('#mobileEditItemBtn').tap()
                        expect(page.locator('#mobileEditItemDialog')).to_be_visible()
                        settle(page)
                        self.assertEqual(view(page), expected_view, 'Opening item controls reset the view')
                        if width == 390:
                            page.set_viewport_size({'width': width, 'height': 680})
                            settle(page)
                            self.assertEqual(view(page), expected_view, 'Resizing the viewport reset the view')
                            page.set_viewport_size({'width': width, 'height': height})
                            settle(page)
                        page.locator('#mobileEditItemDialog [data-mobile-close]').tap()
                        settle(page)
                        self.assertEqual(view(page), expected_view, 'Closing item controls reset the view')
                        self.assertEqual(page.evaluate('testCanvas.getObjects().map(object => object.toObject())'), objects)
                        # Customers can still explicitly reset the view using Fit to screen.
                        page.locator('#mobileCanvasToolsBtn').tap()
                        page.locator('#zoomResetBtn').tap()
                        settle(page)
                        centered = page.evaluate('''() => {
                            const paper = testCanvas.getObjects().find(object => object._isArtboard);
                            const zoom = testCanvas.getZoom(), vpt = testCanvas.viewportTransform;
                            return {x: (paper.left + paper.width / 2) * zoom + vpt[4],
                                    y: (paper.top + paper.height / 2) * zoom + vpt[5],
                                    width: testCanvas.getWidth(), height: testCanvas.getHeight()};
                        }''')
                        self.assertAlmostEqual(centered['x'], centered['width'] / 2, delta=1)
                        self.assertAlmostEqual(centered['y'], centered['height'] / 2, delta=1)
                        context.close()
                self.assertFalse(self.errors, self.errors)
            finally:
                browser.close()

    def test_pinch_zooms_at_fingers_with_limits_and_drag_recovery(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width, height in ((320, 740), (390, 844), (820, 1000), (844, 390)):
                    with self.subTest(width=width, height=height):
                        context, page = self.open_page(browser, width, height)
                        session = context.new_cdp_session(page)
                        stage = page.locator('.upper-canvas').bounding_box()
                        x, y = stage['x'] + stage['width'] * .56, stage['y'] + stage['height'] * .5
                        initial = page.evaluate('''() => ({zoom: testCanvas.getZoom(),
                            viewport: testCanvas.viewportTransform.slice(), scroll: window.scrollY,
                            pageScale: visualViewport.scale,
                            objects: testCanvas.getObjects().map(object => object.toObject())})''')
                        self.pinch(session, x, y, 60, 108, dx=12, dy=10, sequential=width != 320)
                        zoomed = page.evaluate('''() => ({zoom: testCanvas.getZoom(),
                            viewport: testCanvas.viewportTransform.slice(), scroll: window.scrollY,
                            pageScale: visualViewport.scale,
                            objects: testCanvas.getObjects().map(object => object.toObject()),
                            label: document.getElementById('zoomLabel').textContent})''')
                        self.assertAlmostEqual(zoomed['zoom'], initial['zoom'] * 1.8, delta=.002)
                        # The same design point stays under the moving midpoint of the fingers.
                        for axis, coordinate, origin, delta in ((0, x, stage['x'], 12), (1, y, stage['y'], 10)):
                            world = (coordinate - origin - initial['viewport'][4 + axis]) / initial['zoom']
                            self.assertAlmostEqual(world * zoomed['zoom'] + zoomed['viewport'][4 + axis],
                                                   coordinate - origin + delta, delta=1)
                        self.assertEqual(zoomed['label'], f"{int(zoomed['zoom'] * 100 + .5)}%")
                        self.assertEqual(zoomed['objects'], initial['objects'])
                        self.assertEqual(zoomed['scroll'], initial['scroll'])
                        self.assertEqual(zoomed['pageScale'], initial['pageScale'])
                        self.pinch(session, x, y, 108, 60)
                        self.assertAlmostEqual(page.evaluate('testCanvas.getZoom()'), initial['zoom'], delta=.002)
                        self.pinch(session, x, y, 10, 180)
                        self.assertAlmostEqual(page.evaluate('testCanvas.getZoom()'), 1.5, delta=.002)
                        self.pinch(session, x, y, 180, 2)
                        self.assertAlmostEqual(page.evaluate('testCanvas.getZoom()'), initial['zoom'], delta=.002)
                        before_pan = page.evaluate('testCanvas.viewportTransform.slice()')
                        self.touch_drag(session, x, y, 20, 15)
                        after_pan = page.evaluate('testCanvas.viewportTransform.slice()')
                        self.assertAlmostEqual(after_pan[4] - before_pan[4], 20, delta=1)
                        self.assertAlmostEqual(after_pan[5] - before_pan[5], 15, delta=1)
                        self.assertTrue(page.evaluate('testCanvas.selection && testCanvas.mainTouchId === null'))
                        context.close()
                self.assertFalse(self.errors, self.errors)
            finally:
                browser.close()

    def test_pinch_preserves_selected_item_and_recovers_after_cancel(self):
        from playwright.sync_api import sync_playwright, expect

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context, page = self.open_page(browser, 390)
                session = context.new_cdp_session(page)
                page.locator('[data-panel-target="textPanel"]').tap()
                page.locator('.text-preset-card[title="Add a Heading"]').tap()
                expect(page.locator('#mobileInventoryDialog')).to_be_hidden()
                page.wait_for_function('testCanvas.getActiveObject() && !testCanvas.getActiveObject().isEditing')
                original = page.evaluate('''() => {
                    const object = testCanvas.getActiveObject();
                    const rect = testCanvas.upperCanvasEl.getBoundingClientRect();
                    return {x: rect.x + object.oCoords.moveCtl.x, y: rect.y + object.oCoords.moveCtl.y,
                            object: object.toObject()};
                }''')
                # The first finger owns an item drag until the second finger joins.
                first = {'x': original['x'], 'y': original['y'], 'id': 0}
                second = {'x': original['x'] + 60, 'y': original['y'], 'id': 1}
                session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [first]})
                self.assertTrue(page.evaluate('!!testCanvas._currentTransform'))
                session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [first, second]})
                for step in range(1, 6):
                    session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [
                        {**first, 'x': first['x'] - 4 * step}, {**second, 'x': second['x'] + 4 * step}]})
                self.assertEqual(page.evaluate('testCanvas.getActiveObject().toObject()'), original['object'])
                self.assertFalse(page.evaluate('!!testCanvas._currentTransform'))
                # Lifting either finger switches to paper pan, never an item drag.
                second['x'] += 20
                session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': [
                    {**first, 'x': first['x'] - 20}]})
                before_pan = page.evaluate('testCanvas.viewportTransform.slice()')
                second.update(x=second['x'] + 15, y=second['y'] + 12)
                session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [second]})
                after_pan = page.evaluate('testCanvas.viewportTransform.slice()')
                self.assertAlmostEqual(after_pan[4] - before_pan[4], 15, delta=1)
                self.assertAlmostEqual(after_pan[5] - before_pan[5], 12, delta=1)
                session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                self.assertEqual(page.evaluate('testCanvas.getActiveObject().toObject()'), original['object'])
                self.assertFalse(page.evaluate('!!testCanvas.getActiveObject().isEditing'))
                # The same selected item can still be moved after zooming.
                point = page.evaluate('''() => {
                    const object = testCanvas.getActiveObject();
                    const rect = testCanvas.upperCanvasEl.getBoundingClientRect();
                    return {x: rect.x + object.oCoords.moveCtl.x, y: rect.y + object.oCoords.moveCtl.y,
                            left: object.left, top: object.top, zoom: testCanvas.getZoom()};
                }''')
                self.touch_drag(session, point['x'], point['y'], 12, 8)
                moved = page.evaluate('({left: testCanvas.getActiveObject().left, top: testCanvas.getActiveObject().top})')
                self.assertAlmostEqual(moved['left'] - point['left'], 12 / point['zoom'], delta=2)
                self.assertAlmostEqual(moved['top'] - point['top'], 8 / point['zoom'], delta=2)
                page.screenshot(path=str(Path(gettempdir()) / 'balloorina-mobile-canvas-pinch.png'), animations='disabled')
                # Interrupted gestures release Fabric's first finger and restore controls.
                stage = page.locator('.upper-canvas').bounding_box()
                x, y = stage['x'] + stage['width'] * .2, stage['y'] + stage['height'] * .2
                for interruption in ('cancel', 'blur'):
                    with self.subTest(interruption=interruption):
                        first = {'x': x, 'y': y, 'id': 0}
                        second = {'x': x + 60, 'y': y, 'id': 1}
                        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [first]})
                        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [first, second]})
                        if interruption == 'cancel':
                            session.send('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
                        else:
                            page.evaluate("window.dispatchEvent(new Event('blur'))")
                            session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                        self.assertTrue(page.evaluate('''testCanvas.selection && !testCanvas.skipTargetFind &&
                            testCanvas.mainTouchId === null && !testCanvas._currentTransform'''))
                        before_pan = page.evaluate('testCanvas.viewportTransform.slice()')
                        self.touch_drag(session, x, y, 12, 8)
                        after_pan = page.evaluate('testCanvas.viewportTransform.slice()')
                        self.assertAlmostEqual(after_pan[4] - before_pan[4], 12, delta=1)
                        self.assertAlmostEqual(after_pan[5] - before_pan[5], 8, delta=1)
                context.close()
                self.assertFalse(self.errors, self.errors)
            finally:
                browser.close()

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
