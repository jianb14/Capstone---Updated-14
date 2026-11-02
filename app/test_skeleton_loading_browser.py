"""Real geometry, fast requests, navigation and FullCalendar regression coverage."""
import base64
import os
from datetime import date, time
from pathlib import Path
from unittest import skipUnless
from urllib.request import urlopen

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from .models import Booking, ConcernTicket, Package, Payment, Review, User, UserDesign

ENABLED = os.environ.get('RUN_SKELETON_BROWSER') == '1'
EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
ROOT = Path(settings.BASE_DIR)
ARTIFACTS = ROOT / '.booking-followup-check'
PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDOkAAAAASUVORK5CYII='


def assets(page):
    page.add_style_tag(path=str(ROOT / 'static/css/skeleton.css'))
    page.add_script_tag(path=str(ROOT / 'static/js/skeleton.js'))


def calendar_bundle():
    ARTIFACTS.mkdir(exist_ok=True)
    source = ARTIFACTS / 'fullcalendar-6.1.11.js'
    if not source.exists():
        with urlopen('https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js', timeout=30) as response:
            source.write_bytes(response.read())
    return source


@skipUnless(ENABLED, 'Set RUN_SKELETON_BROWSER=1')
class SkeletonLifecycleBrowserTests(SimpleTestCase):
    def test_ownership_abort_dom_replacement_and_dialog_cleanup(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div id="results"><input value="Unsaved draft"><p>Existing results</p></div>'
                    '<div id="other"><p>Other results</p></div><dialog style="transform:translateY(8px)">'
                    '<header><button>Close</button></header><div id="detail">Booking details</div></dialog>')
                assets(page)
                original = page.locator('#results').inner_html()
                page.evaluate("window.first=SiteLoading.start('#results',{delay:0});window.latest=SiteLoading.start('#results',{delay:0});first.finish()")
                expect(page.locator('[data-skeleton-for=results]')).to_be_visible()
                self.assertEqual(page.locator('#results').inner_html(), original)
                expect(page.locator('#results .site-skeleton-layer')).to_have_count(0)
                expect(page.locator('#results input')).to_have_value('Unsaved draft')
                expect(page.locator('[data-skeleton-for=results]')).to_have_attribute('aria-hidden', 'true')
                page.evaluate("window.abort=new AbortController();SiteLoading.start('#other',{delay:0,signal:abort.signal});abort.abort()")
                expect(page.locator('[data-skeleton-for=other]')).to_have_count(0)
                expect(page.locator('[data-skeleton-for=results]')).to_have_count(1)
                page.evaluate("document.querySelector('#results').innerHTML='<p>Fresh results</p>'")
                expect(page.locator('[data-skeleton-for=results] .site-skeleton-shape')).to_have_count(1)
                page.evaluate('latest.finish();latest.finish()')
                expect(page.locator('#results')).not_to_have_attribute('aria-busy', 'true')
                page.evaluate("document.querySelector('dialog').showModal();SiteLoading.start('#detail',{delay:0})")
                expect(page.get_by_role('button', name='Close')).to_be_visible()
                boxes = page.evaluate("() => ({a:document.querySelector('#detail').getBoundingClientRect().toJSON(),b:document.querySelector('[data-skeleton-for=detail]').getBoundingClientRect().toJSON()})")
                for key in ('x', 'y', 'width', 'height'):
                    self.assertAlmostEqual(boxes['a'][key], boxes['b'][key], delta=1)
                page.evaluate("document.querySelector('dialog').close()")
                expect(page.locator('[data-skeleton-for=detail]')).to_have_count(0)
                page.evaluate("SiteLoading.start('#results',{delay:0,timeout:40})")
                expect(page.locator('[data-skeleton-for=results]')).to_have_count(0, timeout=2000)
                page.evaluate("SiteLoading.start('#results',{delay:0});window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
                expect(page.locator('.site-loading-portal')).to_have_count(0)
            finally:
                browser.close()

    def test_fast_requests_do_not_flash_and_slow_requests_do_not_move_content(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<main data-skeleton-page><h1>Ready page</h1><div id="results"><p>Ready results</p></div></main>')
                assets(page)
                page.clock.install()
                box = page.locator('#results').bounding_box()
                page.evaluate("const load=SiteLoading.start('#results');load.finish()")
                page.clock.fast_forward(200)
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                page.evaluate("window.slow=SiteLoading.start('#results')")
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                page.clock.fast_forward(181)
                expect(page.locator('[data-skeleton-for=results]')).to_be_visible()
                self.assertEqual(box, page.locator('#results').bounding_box())
                expect(page.get_by_role('heading', name='Ready page')).to_be_visible()
                page.evaluate('slow.finish()')
                self.assertEqual(box, page.locator('#results').bounding_box())
            finally:
                browser.close()

    def test_actual_card_geometry_themes_responsive_motion_and_no_js(self):
        from playwright.sync_api import expect, sync_playwright
        ARTIFACTS.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page(reduced_motion='reduce')
                html = '<style>body{margin:0;padding:20px;font:16px/1.6 sans-serif}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}.card{padding:16px;border:1px solid #777;border-radius:12px}.card img{width:100%;height:120px;object-fit:cover}@media(max-width:700px){.cards{grid-template-columns:1fr}}</style><h1>Available designs</h1><div class="cards" id="cards">'
                html += f'<article class="card"><img width="320" height="120" src="data:image/png;base64,{PIXEL}" alt="Design"><h3>Birthday design</h3><p>Ready to book</p></article>' * 3 + '</div>'
                page.set_content(html)
                assets(page)
                for width in (390, 768, 1440):
                    for theme in ('light', 'dark'):
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.evaluate("theme=>{document.documentElement.dataset.theme=theme;window.loading=SiteLoading.start('#cards',{variant:'cards',delay:0})}", theme)
                        expect(page.locator('[data-skeleton-for=cards]')).to_be_visible()
                        boxes = page.evaluate("() => ({a:[...document.querySelectorAll('.card img')].map(el=>el.getBoundingClientRect().toJSON()),b:[...document.querySelectorAll('[data-skeleton-kind=media]')].map(el=>el.getBoundingClientRect().toJSON())})")
                        self.assertEqual(len(boxes['b']), 3)
                        for actual, placeholder in zip(boxes['a'], boxes['b']):
                            for key in ('x', 'y', 'width', 'height'):
                                self.assertAlmostEqual(actual[key], placeholder[key], delta=1)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth-innerWidth'), 1)
                        self.assertEqual(page.locator('.site-skeleton-shape').first.evaluate('el=>getComputedStyle(el).animationName'), 'none')
                        page.screenshot(path=str(ARTIFACTS / f'skeleton-matched-{width}-{theme}.png'))
                        page.evaluate('loading.finish()')
                fallback = browser.new_context(java_script_enabled=False)
                no_js = fallback.new_page()
                no_js.set_content(html + '<script>' + (ROOT / 'static/js/skeleton.js').read_text(encoding='utf-8') + '</script>')
                expect(no_js.get_by_role('heading', name='Available designs')).to_be_visible()
                expect(no_js.locator('.site-skeleton-layer')).to_have_count(0)
                fallback.close()
            finally:
                browser.close()

    def test_image_dimensions_error_and_cached_source_replacement(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div id="images"></div>')
                assets(page)
                held = []
                page.route('https://skeleton.test/**', lambda route: held.append(route))
                page.evaluate("document.querySelector('#images').innerHTML='<img id=photo src=https://skeleton.test/photo.png alt=Photo width=120 height=90>'")
                box = page.locator('#photo').bounding_box()
                expect(page.locator('#photo')).to_have_class('site-image-loading')
                self.assertEqual(box, page.locator('#photo').bounding_box())
                held.pop().abort()
                expect(page.locator('#photo')).not_to_have_class('site-image-loading')
                page.evaluate("document.querySelector('#photo').src='https://skeleton.test/second.png'")
                expect(page.locator('#photo')).to_have_class('site-image-loading')
                held.pop().fulfill(status=200, content_type='image/png', body=base64.b64decode(PIXEL))
                expect(page.locator('#photo')).not_to_have_class('site-image-loading')
                page.evaluate("src=>document.querySelector('#photo').src=src", 'data:image/png;base64,' + PIXEL)
                page.wait_for_function("document.querySelector('#photo').complete")
                page.evaluate("SiteLoading.scan(document.documentElement);SiteLoading.scan(document.documentElement)")
                expect(page.locator('#photo')).not_to_have_class('site-image-loading')
                self.assertEqual(box, page.locator('#photo').bounding_box())
            finally:
                browser.close()

    def test_clipped_text_and_controls_are_not_covered_by_media(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div id="data" style="width:300px;position:relative">'
                    '<canvas width="300" height="150"></canvas><button id="close" style="position:absolute;right:8px;top:8px">Close</button>'
                    '<p id="email" style="width:90px;overflow:hidden;white-space:nowrap">very.long.customer.address@example.com</p></div>')
                assets(page)
                checks = page.evaluate("""() => {
                    const load=SiteLoading.start('#data',{delay:0});
                    const button=document.querySelector('#close').getBoundingClientRect();
                    const email=document.querySelector('#email').getBoundingClientRect();
                    const media=[...document.querySelectorAll('[data-skeleton-kind=media]')].map(el=>el.getBoundingClientRect());
                    const text=[...document.querySelectorAll('[data-skeleton-kind=text]')].map(el=>el.getBoundingClientRect());
                    const result={covered:media.some(r=>r.left<button.right&&r.right>button.left&&r.top<button.bottom&&r.bottom>button.top),clipped:text.every(r=>r.right<=email.right+1),count:media.length};
                    load.finish();return result;
                }""")
                self.assertFalse(checks['covered'])
                self.assertTrue(checks['clipped'])
                self.assertGreater(checks['count'], 0)
            finally:
                browser.close()

    def test_append_and_empty_panels_keep_owned_nodes_outside_content(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div id="rows"><article class="notif-item"><p>Existing update</p></article></div><div id="empty"></div>')
                assets(page)
                original = page.locator('#rows').inner_html()
                box = page.locator('.notif-item').bounding_box()
                page.evaluate("window.load=SiteLoading.start('#rows',{mode:'append',delay:0})")
                self.assertEqual(page.locator('#rows').inner_html(), original)
                self.assertEqual(page.locator('.notif-item').bounding_box(), box)
                expect(page.locator('[data-skeleton-mode=append] .site-skeleton-shape')).to_have_count(1)
                page.evaluate("load.finish();window.empty=SiteLoading.start('#empty',{delay:0})")
                self.assertEqual(page.locator('#empty').inner_html(), '')
                expect(page.locator('.site-loading-empty')).to_have_count(1)
                expect(page.locator('.site-loading-empty input,.site-loading-empty table,.site-loading-empty img')).to_have_count(0)
                page.evaluate('empty.finish()')
                expect(page.locator('.site-loading-slot,.site-loading-portal')).to_have_count(0)
            finally:
                browser.close()

    def test_placeholder_tracks_a_finite_entrance_animation(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div id="parent"><div id="data"><canvas width="200" height="80"></canvas></div></div>')
                assets(page)
                checks = page.evaluate("""async () => {
                    const animation=document.querySelector('#parent').animate([{transform:'translateX(40px)'},{transform:'translateX(0)'}],{duration:180,fill:'forwards'});
                    const load=SiteLoading.start('#data',{delay:0});
                    await animation.finished;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
                    const a=document.querySelector('canvas').getBoundingClientRect();
                    const b=document.querySelector('[data-skeleton-kind=media]').getBoundingClientRect();
                    const delta=Math.abs(a.x-b.x)+Math.abs(a.y-b.y);load.finish();return delta;
                }""")
                self.assertLessEqual(checks, 1)
            finally:
                browser.close()

    def test_real_fullcalendar_keeps_grid_when_loader_finishes(self):
        from playwright.sync_api import sync_playwright
        source = calendar_bundle()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page()
                page.set_content('<div style="width:900px"><div id="calendar"></div></div>')
                assets(page)
                page.add_script_tag(path=str(source))
                result = page.evaluate("""() => {
                    const root=document.querySelector('#calendar');
                    const loading=SiteLoading.start(root,{variant:'calendar',delay:0});
                    const childrenBeforeMount=root.childElementCount;
                    const calendar=new FullCalendar.Calendar(root,{initialView:'dayGridMonth',headerToolbar:false,height:'auto'});
                    calendar.render();const before=root.querySelectorAll('table').length;
                    loading.finish();const after=root.querySelectorAll('table').length;
                    const height=root.getBoundingClientRect().height;
                    const refresh=SiteLoading.start(root,{variant:'calendar',delay:0});
                    calendar.next();refresh.finish();const next=root.querySelectorAll('table').length;
                    calendar.destroy();return {childrenBeforeMount,before,after,height,next};
                }""")
                self.assertEqual(result['childrenBeforeMount'], 0)
                self.assertGreaterEqual(result['before'], 3)
                self.assertEqual(result['after'], result['before'])
                self.assertGreater(result['height'], 300)
                self.assertGreaterEqual(result['next'], 3)
            finally:
                browser.close()


@skipUnless(ENABLED, 'Set RUN_SKELETON_BROWSER=1')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class SkeletonIntegrationBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='skeleton-admin', email='admin@skeleton.test', first_name='Admin', role='admin', email_verified=True)
        self.customer = User.objects.create_user(username='skeleton-customer', email='customer@skeleton.test', first_name='Skeleton', last_name='Customer', role='customer', email_verified=True)
        self.booking = Booking.objects.create(user=self.customer, event_date=date(2099, 6, 10), event_time=time(10), event_type='Birthday', event_location='Test venue', package_type='Package A', total_price=5000, status='confirmed')
        self.sessions = {}
        for user in (self.admin, self.customer):
            client = Client()
            client.force_login(user)
            self.sessions[user.pk] = client.cookies[settings.SESSION_COOKIE_NAME].value

    def context(self, playwright, user):
        browser = playwright.chromium.launch(executable_path=EDGE, headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.sessions[user.pk], 'url': self.live_server_url}])
        bundle = calendar_bundle()
        def external(route):
            url = route.request.url
            if url.startswith(self.live_server_url + '/'):
                route.continue_()
            elif 'fullcalendar@6.1.11/index.global.min.js' in url:
                route.fulfill(path=str(bundle), content_type='application/javascript')
            elif 'sweetalert2' in url:
                route.fulfill(content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}}),fire:()=>Promise.resolve({})};')
            else:
                route.abort()
        context.route('**/*', external)
        return browser, context

    def test_real_result_regions_across_admin_customer_and_public_pages(self):
        from playwright.sync_api import expect, sync_playwright
        Package.objects.create(name='Measured package', price=5000, features='Backdrop\nBalloons')
        Payment.objects.create(booking=self.booking, amount=1000, payment_method='gcash', payment_status='verified', transaction_ref='SKELETON-PAID')
        Review.objects.create(user=self.customer, booking=self.booking, rating=5, comment='Measured review content')
        ConcernTicket.objects.create(user=self.customer, subject='Measured concern', message='Test message')
        UserDesign.objects.create(user=self.customer, name='Measured design', canvas_json='{}')
        admin_cases = [('dashboard','#dashboardResults'),('admin_analytics','#analyticsResults'),('admin_booking_list','[data-workspace-content]'),
            ('admin_payment_list','#pmQueues'),('admin_user_list','#userResults'),('admin_reviews','#reviewResults'),
            ('admin_concerns','#adminConcernResults'),('admin_audit_log','#auditLogResults'),('admin_package_list','[data-catalog-workspace]'),
            ('admin_gallery','[data-catalog-workspace]'),('admin_canvas_assets','[data-catalog-workspace]'),('ai_health','#ahRequests'),('admin_calendar','.fc')]
        client_cases = [('customer_profile','#accountContent'),('my_payments','#accountContent'),('my_reviews','#accountContent'),
            ('report_concern','#accountContent'),('my_designs','#designLibraryResults'),('reviews','[data-review-page-content]')]
        with sync_playwright() as p:
            for user, cases in ((self.admin,admin_cases),(self.customer,client_cases)):
                browser, context = self.context(p,user)
                try:
                    page = context.new_page()
                    page.emulate_media(reduced_motion='reduce')
                    for width, theme in ((390,'light'),(1440,'dark')):
                        page.set_viewport_size({'width':width,'height':1100})
                        context.add_init_script(f"localStorage.setItem('balloorina-theme','{theme}')")
                        for name, selector in cases:
                            with self.subTest(route=name,width=width,theme=theme):
                                page.goto(self.live_server_url+reverse(name),wait_until='domcontentloaded')
                                expect(page.locator(selector).first).to_be_visible()
                                result = page.evaluate("""selector => {
                                    const target=document.querySelector(selector), before=target.getBoundingClientRect();
                                    const html=target.innerHTML, overflow=document.documentElement.scrollWidth;
                                    const load=SiteLoading.start(target,{variant:'table',delay:0});
                                    const after=target.getBoundingClientRect();
                                    const result={dom:html===target.innerHTML,width:Math.abs(before.width-after.width),height:Math.abs(before.height-after.height),overflow:document.documentElement.scrollWidth-overflow,inside:target.querySelectorAll('.site-skeleton-layer').length};
                                    load.finish();result.restored=html===target.innerHTML;return result;
                                }""",selector)
                                self.assertTrue(result['dom'],result)
                                self.assertTrue(result['restored'],result)
                                self.assertLessEqual(result['width'],1,result)
                                self.assertLessEqual(result['height'],1,result)
                                self.assertEqual(result['inside'],0,result)
                                self.assertLessEqual(result['overflow'],1,result)
                finally:
                    browser.close()

    def test_booking_calendar_first_month_reload_week_month_in_all_sizes_and_themes(self):
        from playwright.sync_api import expect, sync_playwright
        ARTIFACTS.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser, context = self.context(p, self.customer)
            try:
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for width in (390, 768, 1440):
                    for theme in ('light', 'dark'):
                        context.add_init_script(f"localStorage.setItem('balloorina-theme','{theme}')")
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.goto(self.live_server_url + reverse('booking_page'), wait_until='domcontentloaded')
                        month = page.locator('#booking-calendar-mount .fc-dayGridMonth-view')
                        expect(month).to_be_visible()
                        self.assertGreaterEqual(page.locator('#booking-calendar-mount .fc-daygrid-day').count(), 28)
                        self.assertGreater(page.locator('#booking-calendar-mount').bounding_box()['height'], 250)
                        expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                        page.screenshot(path=str(ARTIFACTS / f'calendar-first-month-{width}-{theme}.png'))
                        page.reload(wait_until='domcontentloaded')
                        expect(month).to_be_visible()
                        page.locator('[data-view=timeGridWeek]').click()
                        expect(page.locator('.fc-timeGridWeek-view')).to_be_visible()
                        page.locator('[data-view=dayGridMonth]').click()
                        expect(month).to_be_visible()
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_navigation_keeps_ready_content_and_never_uses_full_page_mask(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.context(p, self.customer)
            try:
                page = context.new_page()
                held = []
                page.route('**/js/account_tables.js*', lambda route: held.append(route))
                page.goto(self.live_server_url + reverse('customer_profile'), wait_until='commit')
                expect(page.locator('#accountContent')).to_be_visible()
                expect(page.locator('.account-sidebar')).to_be_visible()
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                held.pop().continue_()
                page.wait_for_load_state('domcontentloaded')
                original = page.locator('#accountContent').bounding_box()
                page.route('**/my-payments/', lambda route: held.append(route))
                page.locator('.account-sidebar [data-account-key=my_payments]').click()
                expect(page.locator('.account-navigation-status')).to_be_visible()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page', 'customer_profile')
                self.assertEqual(original, page.locator('#accountContent').bounding_box())
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                held.pop().continue_()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page', 'my_payments')
                page.go_back()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page', 'customer_profile')
                page.goto(self.live_server_url + reverse('home'))
                expect(page.locator('.hero h1')).to_be_visible()
                expect(page.locator('.hero .cta-buttons a')).to_have_count(2)
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                snapshots = []
                page.on('console', lambda message: snapshots.append(message.text) if message.text.startswith('navigation-mask:') else None)
                page.evaluate("""() => window.addEventListener('click',event => {
                    if(event.target.closest('a[href="/about/"]')) console.log('navigation-mask:'+document.querySelectorAll('.site-skeleton-layer').length);
                })""")
                page.locator('.nav-links a[href="/about/"]').click()
                page.wait_for_url('**/about/')
                self.assertEqual(snapshots, ['navigation-mask:0'])
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
            finally:
                browser.close()

    def test_admin_columns_and_dialog_close_while_pending(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.context(p, self.admin)
            try:
                page = context.new_page()
                held = []
                page.goto(self.live_server_url + reverse('admin_user_list'))
                page.wait_for_function("!document.getAnimations().some(a=>a.playState==='running'&&a.effect?.getTiming().iterations!==Infinity)")
                original = page.locator('#userResults').bounding_box()
                page.route('**/staff/users/**', lambda route: held.append(route) if route.request.resource_type == 'fetch' else route.continue_())
                page.locator('#userFilters input[name=search]').fill('Skeleton')
                overlay = page.locator('[data-skeleton-for=userResults]')
                expect(overlay).to_be_visible()
                current = page.locator('#userResults').bounding_box()
                for key in ('x', 'y', 'width', 'height'):
                    self.assertAlmostEqual(original[key], current[key], delta=0.5)
                expect(page.locator('#userResults .site-skeleton-layer')).to_have_count(0)
                expect(page.locator('#userFilters input[name=search]')).to_be_visible()
                self.assertEqual(page.locator('#userResults thead').evaluate('el=>getComputedStyle(el).visibility'), 'visible')
                self.assertGreater(overlay.locator('.site-skeleton-shape').count(), 0)
                page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                coordinates = overlay.locator('.site-skeleton-shape').evaluate_all("""pieces=>{
                    const body=document.querySelector('#userResults tbody').getBoundingClientRect();
                    return {body:body.toJSON(),layer:document.querySelector('[data-skeleton-for=userResults]').getBoundingClientRect().toJSON(),outside:pieces.map(el=>el.getBoundingClientRect().toJSON()).filter(r=>r.top<body.top-1||r.bottom>body.bottom+1)};
                }""")
                page.screenshot(path=str(ARTIFACTS / 'skeleton-actual-admin-users.png'))
                self.assertEqual(coordinates['outside'], [], coordinates)
                held.pop().fulfill(status=503, content_type='application/json', body='{"message":"Please retry"}')
                expect(overlay).to_have_count(0)
                page.locator('#userListFeedback').get_by_role('button', name='Try again').click()
                expect(overlay).to_be_visible()
                held.pop().continue_()
                expect(overlay).to_have_count(0)
                page.locator(f'a.um-view[data-user-id="{self.customer.pk}"]').click()
                expect(page.locator('dialog[open] [data-skeleton-layout=details]')).to_be_visible()
                expect(page.get_by_role('button', name='Close account details')).to_be_visible()
                page.get_by_role('button', name='Close account details').click()
                expect(page.locator('[data-skeleton-layout=details]')).to_have_count(0)
                for route in held:
                    route.abort()
            finally:
                browser.close()

    def test_notifications_and_chat_background_updates_stay_visible(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.context(p, self.customer)
            try:
                page = context.new_page()
                held = []
                page.goto(self.live_server_url + reverse('customer_profile'))
                page.route('**/notifications/**', lambda route: held.append(route))
                page.locator('#notif-bell').click()
                expect(page.locator('[data-skeleton-for]')).to_be_visible()
                held.pop().continue_()
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                page.locator('#notif-bell').click()
                page.route('**/api/support/state/**', lambda route: held.append(route))
                page.locator('#adminChatToggle').click()
                expect(page.locator('[data-skeleton-layout=chat]')).to_be_visible()
                held.pop().continue_()
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                page.clock.install()
                page.clock.fast_forward(16000)
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
                for route in held:
                    route.continue_()
                page.locator('#adminChatToggle').click()
                expect(page.locator('.site-skeleton-layer')).to_have_count(0)
            finally:
                browser.close()
