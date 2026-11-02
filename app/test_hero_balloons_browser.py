"""Opt-in browser checks for shared public/auth decorations, with no account writes."""
import mimetypes
import os
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


@skipUnless(os.environ.get('RUN_HERO_BROWSER') == '1', 'Optional Playwright verification')
class HeroBalloonsBrowserTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.static = Path(settings.BASE_DIR) / 'static'
        cls.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'
        cls.artifacts.mkdir(exist_ok=True)
        cls.pages = {}
        for family, name in (
            ('client', 'home'), ('client', 'about'), ('client', 'services'),
            ('client', 'gallery'), ('client', 'package'),
            ('auth', 'login'), ('auth', 'register'), ('auth', 'forgot_password'),
        ):
            request = RequestFactory().get('/' + name + '/')
            request.user = AnonymousUser()
            request.session = {}
            request._public_business_settings = {
                'site_name': 'Balloorina', 'contact_email': '', 'contact_phone': '',
                'address': '', 'facebook_link': '', 'instagram_link': '',
            }
            cls.pages['/' + name + '/'] = render_to_string(f'{family}/{name}.html', request=request)

    def serve(self, route):
        url = urlsplit(route.request.url)
        if url.netloc == 'decorations.test':
            if url.path in self.pages:
                route.fulfill(content_type='text/html', body=self.pages[url.path])
                return
            if url.path.startswith('/static/'):
                path = (self.static / url.path.removeprefix('/static/')).resolve()
                if path.is_relative_to(self.static.resolve()) and path.is_file():
                    route.fulfill(content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream', body=path.read_bytes())
                    return
        route.abort()

    def launch(self, playwright):
        return playwright.chromium.launch(
            executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)

    def open(self, context, name):
        page = context.new_page()
        page.add_init_script("sessionStorage.setItem('balloorina-welcome-seen','1')")
        page.motion_errors = []
        page.on('pageerror', lambda error: page.motion_errors.append(str(error)))
        page.goto('https://decorations.test/' + name + '/', wait_until='load')
        if name != 'gallery':
            page.wait_for_function("document.querySelector('.balloon-drift')?.getAnimations().length > 0")
        page.wait_for_timeout(180)
        return page

    def tap_decoration(self, page):
        # Freeze only the drift during hit testing, so a moving target is repeatable.
        target = page.evaluate('''() => {
            document.querySelectorAll('.balloon-drift').forEach(el=>el.getAnimations().forEach(a=>a.pause()));
            const blocked='a,button,input,select,textarea,label,summary,[role="button"],[contenteditable],.auth-container';
            const controls=[...document.querySelector('.hero,[data-floating-hero]').querySelectorAll(blocked)].map(el=>el.getBoundingClientRect());
            return [...document.querySelectorAll('.balloon')].map((el,index)=>{
                const box=el.firstElementChild.getBoundingClientRect();
                const x=box.left+box.width/2, y=box.top+box.height*.4;
                const hit=document.elementFromPoint(x,y);
                return {index,x,y,valid:el.offsetWidth && Number(getComputedStyle(el).opacity)>.15 &&
                    x>0 && x<innerWidth && y>0 && y<innerHeight &&
                    hit?.closest('.hero,[data-floating-hero]') && !hit.closest(blocked) &&
                    !controls.some(r=>r.width && r.height && x>=r.left-16 && x<=r.right+16 && y>=r.top-16 && y<=r.bottom+16)};
            }).find(item=>item.valid);
        }''')
        self.assertIsNotNone(target, 'At least one visible decoration must accept a tap')
        before_url = page.url
        page.touchscreen.tap(target['x'], target['y'])
        self.assertEqual(page.url, before_url)
        page.wait_for_function('''index => {
            const el=document.querySelectorAll('.balloon-interaction')[index];
            const matrix=new DOMMatrixReadOnly(getComputedStyle(el).transform);
            return Math.hypot(matrix.m41,matrix.m42)>1;
        }''', arg=target['index'], timeout=1500)
        return target

    def test_all_eight_pages_idle_touch_hover_and_mobile_bounds(self):
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                for width, theme, touch in ((320, 'light', True), (390, 'dark', True),
                                            (820, 'light', True), (1440, 'dark', False)):
                    context = browser.new_context(viewport={'width': width, 'height': 900},
                        has_touch=touch, is_mobile=touch, reduced_motion='no-preference')
                    context.add_init_script(f"localStorage.setItem('balloorina-theme', '{theme}')")
                    context.route('**/*', self.serve)
                    for name in ('home', 'about', 'services', 'gallery', 'package', 'login', 'register', 'forgot_password'):
                        with self.subTest(width=width, page=name, touch=touch):
                            page = self.open(context, name)
                            self.assertEqual(page.locator('html').get_attribute('data-theme') == 'light', theme == 'light')
                            if name == 'gallery':
                                expect(page.locator('.hero-balloons,.balloon')).to_have_count(0)
                                expect(page.get_by_role('heading', name='Our Gallery')).to_be_visible()
                                self.assertEqual(page.motion_errors, [])
                                page.close()
                                continue
                            expect(page.locator('.hero-balloons')).to_have_count(1)
                            expect(page.locator('.hero-balloons')).to_have_attribute('aria-hidden', 'true')
                            expect(page.locator('.hero-balloons')).to_have_css('pointer-events', 'none')
                            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth-innerWidth'), 1)
                            if width < 641:
                                expect(page.locator('.balloon')).to_have_count(8)
                                bounds = page.evaluate('''() => {
                                    const scene=document.querySelector('.hero,[data-floating-hero]').getBoundingClientRect();
                                    return [0,.25,.5,.75].flatMap(phase=>{
                                        document.querySelectorAll('.balloon-drift').forEach(el=>el.getAnimations().forEach(a=>{
                                            a.pause();const t=a.effect.getTiming();a.currentTime=t.delay+t.duration*(1+phase);
                                        }));
                                        return [...document.querySelectorAll('.balloon img')].map(el=>{
                                            const r=el.getBoundingClientRect();
                                            return {left:r.left-scene.left,right:scene.right-r.right,top:r.top-scene.top,bottom:scene.bottom-r.bottom};
                                        });
                                    });
                                }''')
                                self.assertTrue(all(min(box.values()) >= -2 for box in bounds), bounds)
                            drift_changes = page.locator('.balloon-drift').evaluate_all('''elements=>elements.filter(el=>el.offsetWidth).map(el=>{
                                const animation=el.getAnimations()[0], before=getComputedStyle(el).transform;
                                animation.currentTime+=1100;
                                return before!==getComputedStyle(el).transform;
                            })''')
                            self.assertTrue(any(drift_changes))
                            if touch:
                                target = self.tap_decoration(page)
                                if width < 641 and name in ('login', 'register'):
                                    self.assertEqual(target['index'], 0, 'The first balloon must be clear of the back link')
                            else:
                                point = page.locator('.balloon:visible .balloon-drift').first.bounding_box()
                                page.mouse.move(point['x'] + point['width'] / 2, point['y'] + point['height'] * .4)
                                page.wait_for_function("[...document.querySelectorAll('.balloon-interaction')].some(el=>getComputedStyle(el).transform!=='none')")
                            self.assertEqual(page.motion_errors, [])
                            if width == 390 and name in ('home', 'gallery', 'login'):
                                page.screenshot(path=str(self.artifacts / f'floating-touch-{name}-{width}.png'))
                            page.close()
                    context.close()
            finally:
                browser.close()

    def test_touch_settles_controls_still_work_and_reduced_motion_stays_static(self):
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as playwright:
            browser = self.launch(playwright)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True,
                    is_mobile=True, reduced_motion='no-preference')
                context.route('**/*', self.serve)
                for name in ('home', 'login', 'register', 'forgot_password'):
                    with self.subTest(page=name):
                        page = self.open(context, name)
                        self.tap_decoration(page)
                        page.wait_for_function("[...document.querySelectorAll('.balloon-interaction')].every(el=>getComputedStyle(el).transform==='none')", timeout=4000)
                        if name == 'home':
                            # A native touch swipe must still scroll the page.
                            cdp = context.new_cdp_session(page)
                            cdp.send('Input.dispatchTouchEvent', {'type':'touchStart',
                                'touchPoints':[{'x':195, 'y':700}]})
                            for y in (650, 590, 520, 440, 350):
                                cdp.send('Input.dispatchTouchEvent', {'type':'touchMove',
                                    'touchPoints':[{'x':195, 'y':y}]})
                            cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd', 'touchPoints':[]})
                            page.wait_for_function('scrollY>100')
                            page.evaluate('scrollTo(0,0)')
                            cdp.detach()
                        if name in ('login', 'register', 'forgot_password'):
                            field = page.locator('input[type=email]')
                            field.tap()
                            expect(field).to_be_focused()
                            self.assertTrue(page.locator('.balloon-interaction').evaluate_all("elements=>elements.every(el=>getComputedStyle(el).transform==='none')"))
                        page.emulate_media(reduced_motion='reduce')
                        page.wait_for_function("document.querySelector('.hero-balloons').getAnimations({subtree:true}).length===0")
                        page.locator('.hero,[data-floating-hero]').dispatch_event('pointerdown',
                            {'pointerType':'touch', 'isPrimary':True, 'button':0, 'clientX':60, 'clientY':70})
                        self.assertTrue(page.locator('.balloon-interaction').evaluate_all("elements=>elements.every(el=>getComputedStyle(el).transform==='none')"))
                        page.emulate_media(reduced_motion='no-preference')
                        for width in (820, 320, 640, 390):
                            page.set_viewport_size({'width':width, 'height':844})
                            expect(page.locator('.hero-balloons')).to_have_count(1)
                            expect(page.locator('.balloon')).to_have_count(8 if width < 641 else 29 if name in ('login','register','forgot_password') else 4 if name == 'gallery' else 23)
                        page.close()
                context.close()
            finally:
                browser.close()
