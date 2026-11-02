"""Opt-in coverage for entry, reloads, intro rendering and its escape paths."""
import mimetypes
import os
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


@skipUnless(os.environ.get('RUN_WELCOME_BROWSER') == '1', 'Set RUN_WELCOME_BROWSER=1')
class WelcomeBrowserTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.static = Path(settings.BASE_DIR) / 'static'
        cls.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        cls.artifacts.mkdir(exist_ok=True)
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        request.session = {}
        request._public_business_settings = {
            'site_name': 'Balloorina', 'contact_email': '', 'contact_phone': '',
            'address': '', 'facebook_link': '', 'instagram_link': '',
        }
        cls.html = render_to_string('client/home.html', request=request)

    def serve(self, route):
        url = urlsplit(route.request.url)
        if url.netloc == 'welcome.test':
            if url.path in ('/', '/about/'):
                route.fulfill(content_type='text/html', body=self.html)
                return
            if url.path.startswith('/static/'):
                path = (self.static / url.path.removeprefix('/static/')).resolve()
                if path.is_relative_to(self.static.resolve()) and path.is_file():
                    route.fulfill(content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream', body=path.read_bytes())
                    return
        route.abort()

    def launch(self, playwright):
        edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
        return playwright.chromium.launch(**({'executable_path': edge} if Path(edge).is_file() else {}), headless=True)

    def context(self, browser, **kwargs):
        context = browser.new_context(**kwargs)
        context.route('**/*', self.serve)
        return context

    def assert_released(self, page):
        from playwright.sync_api import expect
        expect(page.locator('#siteWelcome')).to_have_count(0)
        expect(page.locator('html')).not_to_have_attribute('data-welcome-active', '')
        expect(page.get_by_role('heading', name='Turning Moments Into Elegant Celebrations.')).to_be_visible()
        self.assertFalse(page.evaluate("document.querySelector('.navbar').inert"))

    def test_photo_straightens_without_reversing_and_slides_accelerate(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context = self.context(browser, viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.clock.install(time=1000000)
                page.clock.pause_at(1000001)
                page.goto('https://welcome.test/')
                alignment = page.locator('.welcome-screen__film-window').evaluate('''el=>{
                    const animation=el.getAnimations()[0]; animation.pause();
                    return [0,150,400,700,1000,1300,1600,1850].map(time=>{
                        animation.currentTime=time;
                        const matrix=new DOMMatrixReadOnly(getComputedStyle(el).transform);
                        const box=el.getBoundingClientRect();
                        return {angle:Math.atan2(matrix.b,matrix.a)*180/Math.PI,
                            centerX:box.x+box.width/2,centerY:box.y+box.height/2};
                    });
                }''')
                self.assertAlmostEqual(alignment[0]['angle'], -3, places=3)
                self.assertAlmostEqual(alignment[-1]['angle'], 0, places=3)
                self.assertTrue(all(a['angle'] <= b['angle'] + .0001 for a,b in zip(alignment,alignment[1:])))
                for sample in alignment:
                    self.assertLessEqual(sample['angle'], .001)
                    self.assertAlmostEqual(sample['centerX'], 720, delta=1)
                    self.assertAlmostEqual(sample['centerY'], 450, delta=1)
                progress = page.locator('.welcome-screen__film-strip').evaluate('''el=>{
                    const animation=el.getAnimations()[0]; animation.pause();
                    return [100,440,780,1120,1460,1800].map(time=>{
                        animation.currentTime=time;
                        return -new DOMMatrixReadOnly(getComputedStyle(el).transform).m42/el.offsetHeight;
                    });
                }''')
                self.assertAlmostEqual(progress[0], 0, places=3)
                self.assertAlmostEqual(progress[-1], 5, places=3)
                distances = [b-a for a,b in zip(progress,progress[1:])]
                self.assertTrue(all(a < b for a,b in zip(distances,distances[1:])), distances)
                self.assertGreater(distances[-1], distances[0]*3)
                page.keyboard.press('Escape')
                self.assert_released(page)
                context.close()
            finally:
                browser.close()

    def test_letter_fade_is_staggered_and_intro_images_stay_under_150_kib(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context = self.context(browser)
                page = context.new_page()
                page.clock.install(time=1000000)
                page.clock.pause_at(1000001)
                page.goto('https://welcome.test/')
                expect(page.locator('#siteWelcome')).to_have_attribute('data-welcome-phase', 'film')
                expect(page.locator('.welcome-screen__film-frame')).to_have_count(6)
                expect(page.get_by_role('button', name='Enter website')).to_be_hidden()
                page.clock.fast_forward(1900)
                expect(page.locator('#siteWelcome')).to_have_attribute('data-welcome-phase', 'portrait')
                letters = page.locator('#welcomeTitle .welcome-screen__letter')
                self.assertEqual(letters.all_text_contents(), list('Balloorina'))
                states = letters.evaluate_all('''elements => elements.map(el => {
                    const animation=el.getAnimations()[0];
                    animation.pause(); animation.currentTime=450;
                    return {delay:animation.effect.getTiming().delay, opacity:Number(getComputedStyle(el).opacity)};
                })''')
                self.assertTrue(all(a['delay'] < b['delay'] for a,b in zip(states,states[1:])))
                self.assertGreater(states[0]['opacity'], states[4]['opacity'])
                self.assertEqual(states[-1]['opacity'], 0)
                letters.evaluate_all('elements=>elements.forEach(el=>el.getAnimations()[0].currentTime=1800)')
                self.assertTrue(all(value == 1 for value in letters.evaluate_all('els=>els.map(el=>Number(getComputedStyle(el).opacity))')))
                expect(page.locator('#welcomeTitle')).to_have_css('font-family', 'Poppins, sans-serif')
                images = page.locator('.welcome-screen__card img').evaluate_all('''els=>els.map(el=>({src:new URL(el.currentSrc).pathname,
                    priority:el.fetchPriority,loaded:el.naturalWidth}))''')
                self.assertTrue(all(item['src'].startswith('/static/images/welcome/') and item['src'].endswith('.webp') for item in images))
                self.assertTrue(all(item['loaded'] and item['priority'] == 'high' for item in images))
                self.assertLess(sum(file.stat().st_size for file in (self.static / 'images/welcome').glob('*.webp')), 150 * 1024)
                # Verify the missing middle section and the entire sequence, including its last frame.
                page.clock.fast_forward(2000)
                expect(page.locator('#siteWelcome')).to_have_attribute('data-welcome-phase', 'retract')
                window = page.locator('.welcome-screen__film-window')
                expect(window).to_have_css('animation-name', 'welcome-film-retract')
                page.clock.fast_forward(1000)
                expect(page.locator('#siteWelcome')).to_have_attribute('data-welcome-phase', 'collage')
                expect(page.locator('.welcome-screen__film')).to_be_hidden()
                expect(page.get_by_role('button', name='Enter website')).to_be_visible()
                page.clock.fast_forward(2400)
                expect(page.locator('#siteWelcome')).to_have_attribute('data-leaving', '')
                expect(page.locator('.welcome-screen__panel')).to_have_count(4)
                page.clock.fast_forward(1800)
                self.assert_released(page)
                context.close()
            finally:
                browser.close()

    def test_themes_responsive_geometry_and_skip(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width, height in ((320, 568), (390, 844), (768, 1024), (1440, 900),
                                      (1920, 1080), (844, 390), (568, 320), (320, 400)):
                    for theme in ('dark', 'light'):
                        with self.subTest(width=width, height=height, theme=theme):
                            context = self.context(browser, viewport={'width': width, 'height': height})
                            context.add_init_script(f"localStorage.setItem('balloorina-theme', '{theme}')")
                            page = context.new_page()
                            # Hold the intro's timers during geometry/screenshots; auto-exit is tested separately.
                            page.clock.install(time=1000000)
                            page.clock.pause_at(1000001)
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto('https://welcome.test/', wait_until='load')
                            dialog = page.get_by_role('dialog', name='Balloorina')
                            expect(dialog).to_be_visible()
                            expect(dialog).to_have_css('background-color', page.locator('body').evaluate('el => getComputedStyle(el).backgroundColor'))
                            self.assertTrue(page.evaluate("document.querySelector('#siteWelcome').matches(':modal')"))
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth-innerWidth'), 1)
                            expect(page.locator('.welcome-screen__counter,.welcome-screen__digits')).to_have_count(0)
                            expect(page.locator('#welcomeTitle img')).to_have_count(0)
                            expect(page.locator('#welcomeTitle .welcome-screen__brand')).to_have_text('Balloorina')
                            expect(page.locator('#welcomeTitle')).to_have_css('font-family', 'Poppins, sans-serif')
                            expect(page.get_by_role('button', name='Enter website')).to_be_hidden()
                            page.clock.run_for(2400)
                            dialog.evaluate('el => el.getAnimations({subtree:true}).forEach(a => {if(a.effect.getTiming().iterations === Infinity) a.pause(); else a.finish();})')
                            film = page.locator('.welcome-screen__film').bounding_box()
                            self.assertAlmostEqual(film['x'] + film['width']/2, width/2, delta=1)
                            self.assertAlmostEqual(film['y'] + film['height']/2, height/2, delta=1)
                            if width in (390,1440):
                                page.screenshot(path=str(self.artifacts / f'welcome-portrait-{width}-{theme}.png'))
                            page.clock.fast_forward(2600)
                            expect(dialog).to_have_attribute('data-welcome-phase', 'collage')
                            expect(page.get_by_role('button', name='Enter website')).to_be_visible()
                            dialog.evaluate('el => el.getAnimations({subtree:true}).forEach(a => {if(a.effect.getTiming().iterations === Infinity) a.pause(); else a.finish();})')
                            bounds = page.locator('.welcome-screen__title,.welcome-screen__description,.welcome-screen__enter,.welcome-screen__skip,.welcome-screen__note').evaluate_all('''elements => elements.map(el => {
                                const r = el.getBoundingClientRect();
                                return {left:r.left, top:r.top, right:r.right, bottom:r.bottom};
                            })''')
                            for box in bounds:
                                self.assertGreaterEqual(box['left'], 0)
                                self.assertGreaterEqual(box['top'], 0)
                                self.assertLessEqual(box['right'], width)
                                self.assertLessEqual(box['bottom'], height)
                            if width in (390, 1440):
                                page.screenshot(path=str(self.artifacts / f'welcome-collage-{width}-{theme}.png'))
                            page.get_by_role('button', name='Skip intro').click()
                            expect(page.locator('.welcome-screen__panel')).to_have_count(4)
                            page.clock.run_for(1800)
                            self.assert_released(page)
                            self.assertEqual(errors, [])
                            context.close()
            finally:
                browser.close()

    def test_auto_exit_session_navigation_and_keyboard(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context = self.context(browser)
                page = context.new_page()
                page.goto('https://welcome.test/')
                expect(page.get_by_role('dialog')).to_be_focused()
                page.keyboard.press('Tab')
                expect(page.get_by_role('button', name='Skip intro')).to_be_focused()
                expect(page.locator('#siteWelcome')).to_have_count(0, timeout=9000)
                self.assert_released(page)
                for url in ('https://welcome.test/about/', 'https://welcome.test/'):
                    page.goto(url)
                    expect(page.locator('#siteWelcome')).to_have_count(0)
                page.reload()
                expect(page.get_by_role('dialog')).to_be_visible()
                self.assertEqual(page.evaluate("sessionStorage.getItem('balloorina-welcome-seen')"), '1')
                page.keyboard.press('Escape')
                self.assert_released(page)
                # A cache-bypassing reload must replay even with the old session flag present.
                cdp = context.new_cdp_session(page)
                cdp.send('Network.setCacheDisabled', {'cacheDisabled': True})
                cdp.send('Page.reload', {'ignoreCache': True})
                expect(page.get_by_role('dialog')).to_be_visible()
                page.get_by_role('button', name='Skip intro').click()
                self.assert_released(page)
                page.reload()
                expect(page.get_by_role('dialog')).to_be_visible()
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
                self.assert_released(page)
                context.close()
            finally:
                browser.close()

    def test_four_panel_exit_freezes_current_scene_without_a_blank_frame(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context = self.context(browser, viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.clock.install(time=1000000)
                page.clock.pause_at(1000001)
                page.goto('https://welcome.test/')
                page.clock.fast_forward(5000)
                page.locator('#siteWelcome').evaluate('el => el.getAnimations({subtree:true}).forEach(a => {if(a.effect.getTiming().iterations === Infinity) a.pause(); else a.finish();})')
                before = page.locator('.welcome-screen__track').evaluate_all('els => els.map(el=>getComputedStyle(el).transform)')
                page.get_by_role('button', name='Enter website').click()
                expect(page.locator('.welcome-screen__panel')).to_have_count(4)
                # visibility:hidden on a parent lets explicitly visible children leak through.
                expect(page.locator('#siteWelcome > .welcome-screen__scene .welcome-screen__collage')).to_be_hidden()
                self.assertEqual(page.locator('#siteWelcome > .welcome-screen__scene').evaluate('el=>getComputedStyle(el).display'), 'none')
                self.assertEqual(page.locator('.welcome-screen__snapshot .welcome-screen__track').evaluate_all('els=>els.map(el=>el.style.transform)'), before * 4)
                # Pause at the split: every pixel remains covered by its original scene slice.
                panels = page.locator('.welcome-screen__panel').evaluate_all('''els=>els.map(el=>{
                    const animation=el.getAnimations()[0]; animation.pause(); animation.currentTime=0;
                    return {width:el.getBoundingClientRect().width, delay:animation.effect.getTiming().delay,
                        duplicateIds:el.querySelectorAll('[id]').length};
                })''')
                self.assertEqual([panel['width'] for panel in panels], [360] * 4)
                self.assertEqual([panel['delay'] for panel in panels], [0, 85, 170, 255])
                self.assertEqual(page.evaluate('''() => {
                    const ids=[...document.querySelectorAll('#siteWelcome [id]')].map(el=>el.id);
                    return ids.length === new Set(ids).size;
                }'''), True)
                # Sample partway through: delayed slices occupy different vertical positions.
                positions = page.locator('.welcome-screen__panel').evaluate_all('''els=>els.map(el=>{
                    el.getAnimations()[0].currentTime=650;
                    return el.getBoundingClientRect().top;
                })''')
                self.assertLess(positions[0], positions[1])
                self.assertLess(positions[1], positions[2])
                self.assertLess(positions[2], positions[3])
                page.screenshot(path=str(self.artifacts / 'welcome-four-panel-exit.png'))
                page.clock.run_for(1800)
                self.assert_released(page)
                context.close()
            finally:
                browser.close()

    def test_reduced_motion_no_js_missing_assets_and_storage(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context = self.context(browser, reduced_motion='reduce')
                page = context.new_page()
                page.goto('https://welcome.test/')
                expect(page.locator('#siteWelcome')).to_have_count(0, timeout=1000)
                self.assert_released(page)
                context.close()

                context = self.context(browser, java_script_enabled=False)
                page = context.new_page()
                page.goto('https://welcome.test/')
                expect(page.locator('#siteWelcome')).to_be_hidden()
                expect(page.locator('.hero h1')).to_be_visible()
                context.close()

                for asset in ('welcome.css', 'welcome.js'):
                    context = self.context(browser)
                    context.route('**/' + asset + '?*', lambda route: route.abort())
                    page = context.new_page()
                    page.goto('https://welcome.test/')
                    expect(page.locator('#siteWelcome')).not_to_be_visible()
                    expect(page.locator('.hero h1')).to_be_visible()
                    context.close()

                context = self.context(browser)
                context.add_init_script("Object.defineProperty(window, 'sessionStorage', {get(){throw new Error('Storage blocked')}})")
                page = context.new_page()
                page.goto('https://welcome.test/')
                expect(page.get_by_role('dialog')).to_be_visible()
                # Disabled storage must not prevent completion.
                expect(page.locator('#siteWelcome')).to_have_count(0, timeout=9000)
                self.assert_released(page)
                context.close()

                context = self.context(browser)
                context.route('**/images/welcome/*.webp', lambda route: route.abort())
                page = context.new_page()
                page.goto('https://welcome.test/')
                expect(page.get_by_role('dialog')).to_be_visible()
                page.emulate_media(reduced_motion='reduce')
                self.assert_released(page)
                context.close()
            finally:
                browser.close()
