"""RUN_SITE_GUIDE_BROWSER=1 enables spotlight feature-tour browser checks."""
import os
from contextlib import contextmanager
from datetime import timedelta, time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.template.loader import render_to_string
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, User


@skipUnless(os.environ.get('RUN_SITE_GUIDE_BROWSER')=='1','Optional Playwright verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class SiteGuideBrowserTests(StaticLiveServerTestCase):
    @contextmanager
    def browser_context(self,**options):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            with browser.new_context(**options) as context:
                context.set_default_timeout(7000)
                yield context
            browser.close()

    def fixture(self,context,body=None):
        base=Path(settings.BASE_DIR)
        markup=render_to_string('components/site_guide.html',{'guide_page':'booking_page'})
        source=(base/'static/js/site_guide.js').read_text(encoding='utf-8')
        content=(base/'static/js/site_guide_content.js').read_text(encoding='utf-8')
        css=(base/'static/css/site_guide.css').read_text(encoding='utf-8')
        body=body or '''<button type="button" class="site-guide-launch" data-site-guide-start>Guide</button>
        <section class="booking-calendar-panel"><div id="booking-calendar" style="height:160px;background:#fff">Events calendar</div>
        <div class="cal-toolbar" style="margin-top:30px;height:55px;background:#fff"><button type="button" onclick="window.backgroundClicks=(window.backgroundClicks||0)+1">Calendar action</button></div>
        <div class="calendar-legend" style="margin-top:30px;height:40px;background:#fff">Booked</div></section>
        <input id="unrelated" placeholder="Not required by the tour">'''
        html=f'''<!doctype html><html data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
        body{{margin:0;padding:20px;background:rgb(240,240,240);font:14px Arial}}button,input{{min-height:44px}}[hidden]{{display:none!important}}{css}</style></head>
        <body>{body}{markup}<script>{content}</script><script>{source}</script></body></html>'''
        context.route('http://guide.test/**',lambda route:route.fulfill(content_type='text/html',body=html))
        page=context.new_page();page.goto('http://guide.test/')
        return page

    def test_next_back_and_done_do_not_require_form_completion(self):
        from playwright.sync_api import expect
        with self.browser_context(viewport={'width':1280,'height':900},reduced_motion='reduce') as context:
            page=self.fixture(context);panel=page.locator('[data-guide-panel]')
            expect(panel).to_be_hidden()
            page.get_by_role('button',name='Guide',exact=True).click()
            expect(page.get_by_role('button',name='Next',exact=True)).to_be_visible()
            expect(page.locator('[data-guide-progress]')).to_have_text('1 of 3')
            expect(page.locator('[data-guide-title]')).to_have_text('Events calendar')
            expect(page.get_by_role('button',name='Back',exact=True)).to_be_disabled()
            page.evaluate('document.getElementById("unrelated").value="Prefilled value";document.getElementById("unrelated").dispatchEvent(new Event("change",{bubbles:true}))')
            expect(page.locator('[data-guide-progress]')).to_have_text('1 of 3')
            page.get_by_role('button',name='Next',exact=True).click()
            expect(page.locator('[data-guide-title]')).to_have_text('Calendar controls')
            page.get_by_role('button',name='Back',exact=True).click()
            expect(page.locator('[data-guide-title]')).to_have_text('Events calendar')
            page.get_by_role('button',name='Next',exact=True).click()
            page.get_by_role('button',name='Next',exact=True).click()
            expect(page.locator('[data-guide-progress]')).to_have_text('3 of 3')
            page.get_by_role('button',name='Done',exact=True).click()
            expect(panel).to_be_hidden()
            expect(page.get_by_role('button',name='Guide',exact=True)).to_be_focused()
            self.assertEqual(page.locator('#unrelated').input_value(),'Prefilled value')
            page.reload();expect(panel).to_be_hidden()

    def test_spotlight_dimming_and_blocked_background_clicks(self):
        from io import BytesIO
        from PIL import Image
        with self.browser_context(viewport={'width':1280,'height':900},reduced_motion='reduce') as context:
            page=self.fixture(context);page.get_by_role('button',name='Guide',exact=True).click()
            self.assertTrue(page.locator('#siteGuide').evaluate('element=>element.matches(":modal")'))
            box=page.locator('#booking-calendar').bounding_box()
            picture=Image.open(BytesIO(page.screenshot())).convert('RGB')
            lit=picture.getpixel((int(box['x']+box['width']/2),int(box['y']+box['height']-12)))
            dim=picture.getpixel((1260,880))
            self.assertGreater(min(lit),220)
            self.assertLess(max(dim),150)
            action=page.get_by_role('button',name='Calendar action',exact=True).bounding_box()
            page.mouse.click(action['x']+action['width']/2,action['y']+action['height']/2)
            self.assertEqual(page.evaluate('window.backgroundClicks||0'),0)

    def test_application_shortcuts_are_blocked_but_tour_buttons_work_with_keyboard(self):
        from playwright.sync_api import expect
        with self.browser_context(viewport={'width':1280,'height':900},reduced_motion='reduce') as context:
            page=self.fixture(context)
            page.evaluate('''() => {
                window.backgroundShortcuts=[];
                document.addEventListener('keydown',event=>{
                    window.backgroundShortcuts.push(event.key);
                    if(event.code==='Space')event.preventDefault();
                });
            }''')
            page.get_by_role('button',name='Guide',exact=True).click()
            page.keyboard.press('Delete');page.keyboard.press('ArrowRight');page.keyboard.press('Control+z')
            self.assertEqual(page.evaluate('window.backgroundShortcuts'),[])
            page.get_by_role('button',name='Next',exact=True).press('Space')
            expect(page.locator('[data-guide-progress]')).to_have_text('2 of 3')
            page.get_by_role('button',name='Next',exact=True).press('Enter')
            expect(page.locator('[data-guide-progress]')).to_have_text('3 of 3')
            self.assertEqual(page.evaluate('window.backgroundShortcuts'),[])

    def test_keyboard_stays_in_tour_and_escape_preserves_underlying_dialog(self):
        from playwright.sync_api import expect
        body='''<button class="site-guide-launch" data-site-guide-start>Guide</button><dialog id="bookingModalOverlay"><header class="modal-header"><button class="site-guide-launch" data-site-guide-start>Form Guide</button></header>
        <div class="stepper-wrapper">Event Details / Package / Design / Review</div><div id="step-1"><div class="form-grid"><input id="event_location" value="Existing venue"><div id="eventTypeCustomSelect">Occasion</div><input id="event_date" type="date"></div></div></dialog>'''
        with self.browser_context(viewport={'width':390,'height':844},reduced_motion='reduce') as context:
            page=self.fixture(context,body);page.evaluate('document.getElementById("bookingModalOverlay").showModal()')
            launcher=page.get_by_role('button',name='Form Guide',exact=True);launcher.press('Enter')
            expect(page.locator('[data-guide-panel]')).to_be_visible()
            for _ in range(8):
                page.keyboard.press('Tab')
                self.assertTrue(page.locator('[data-guide-panel]').evaluate('element=>element.contains(document.activeElement)'))
            page.keyboard.press('Escape')
            expect(page.locator('[data-guide-panel]')).to_be_hidden()
            self.assertTrue(page.locator('#bookingModalOverlay').evaluate('element=>element.open'))
            expect(launcher).to_be_focused()
            self.assertEqual(page.locator('#event_location').input_value(),'Existing venue')

    def test_hidden_removed_targets_and_scroll_styles_cleanup(self):
        from playwright.sync_api import expect
        with self.browser_context(viewport={'width':390,'height':844},reduced_motion='reduce') as context:
            page=self.fixture(context)
            page.evaluate('document.querySelector(".calendar-legend").hidden=true;document.body.style.overflow="clip"')
            page.get_by_role('button',name='Guide',exact=True).click()
            expect(page.locator('[data-guide-progress]')).to_have_text('1 of 2')
            page.evaluate('document.getElementById("booking-calendar").remove()')
            expect(page.locator('[data-guide-panel]')).to_be_hidden()
            self.assertEqual(page.evaluate('document.body.style.overflow'),'clip')

    def test_mobile_geometry_and_screenshot_mask_alignment(self):
        from playwright.sync_api import expect
        with self.browser_context(viewport={'width':320,'height':568},is_mobile=True,has_touch=True,reduced_motion='reduce') as context:
            page=self.fixture(context);page.get_by_role('button',name='Guide',exact=True).tap()
            for width,height in ((320,568),(390,844),(768,900)):
                page.set_viewport_size({'width':width,'height':height})
                expect(page.locator('[data-guide-panel]')).to_be_visible();page.wait_for_timeout(80)
                bubble=page.locator('[data-guide-panel]').bounding_box()
                self.assertGreaterEqual(bubble['x'],0);self.assertGreaterEqual(bubble['y'],0)
                self.assertLessEqual(bubble['x']+bubble['width'],width)
                self.assertLessEqual(bubble['y']+bubble['height'],height)
                hole=page.locator('[data-guide-hole]').evaluate('element=>({x:Number(element.getAttribute("x")),y:Number(element.getAttribute("y")),width:Number(element.getAttribute("width")),height:Number(element.getAttribute("height"))})')
                target=page.locator('#booking-calendar').bounding_box()
                self.assertLessEqual(hole['x'],target['x']);self.assertGreaterEqual(hole['width'],target['width'])

    def test_motion_and_rapid_close_restore_interaction_without_stale_callbacks(self):
        from playwright.sync_api import expect
        with self.browser_context(viewport={'width':1280,'height':900},reduced_motion='no-preference') as context:
            page=self.fixture(context);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.get_by_role('button',name='Guide',exact=True).click()
            self.assertTrue(page.locator('[data-guide-shade]').evaluate('element=>element.getAnimations().some(animation=>animation.effect.getTiming().duration>0)'))
            page.get_by_role('button',name='Next',exact=True).click()
            self.assertTrue(page.locator('[data-guide-hole]').evaluate('element=>element.getAnimations().some(animation=>animation.effect.getTiming().duration>0)'))
            page.get_by_role('button',name='Back',exact=True).click()
            page.get_by_role('button',name='Next',exact=True).click()
            page.keyboard.press('Escape')
            page.evaluate('document.dispatchEvent(new CustomEvent("account:unmounting"))')
            expect(page.locator('[data-guide-panel]')).to_be_hidden()
            self.assertEqual(page.evaluate('document.body.style.overflow'),'')
            page.get_by_role('button',name='Guide',exact=True).click()
            page.wait_for_timeout(300)
            expect(page.locator('[data-guide-panel]')).to_be_visible()
            page.keyboard.press('Escape')
            page.emulate_media(reduced_motion='reduce')
            expect(page.locator('[data-guide-panel]')).to_be_hidden()
            self.assertEqual(page.evaluate('document.body.style.overflow'),'')
            self.assertEqual(errors,[])

    def test_reduced_motion_keeps_tour_navigation_immediate(self):
        from playwright.sync_api import expect
        with self.browser_context(viewport={'width':390,'height':844},reduced_motion='reduce') as context:
            page=self.fixture(context);page.get_by_role('button',name='Guide',exact=True).click()
            page.get_by_role('button',name='Next',exact=True).click()
            self.assertEqual(page.locator('#siteGuide').evaluate('element=>element.getAnimations({subtree:true}).filter(animation=>animation.playState==="running").length'),0)
            page.keyboard.press('Escape');expect(page.locator('[data-guide-panel]')).to_be_hidden()

    def test_no_guides_on_unrelated_pages_and_account_navigation_cleanup(self):
        from playwright.sync_api import expect
        user=User.objects.create_user(username='tour-scope',email='tour@example.com',role='customer',email_verified=True)
        self.client.force_login(user)
        with self.browser_context(viewport={'width':1280,'height':900},reduced_motion='reduce') as context:
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            page=context.new_page()
            for route in ('home','about','package','gallery','login','register'):
                page.goto(self.live_server_url+reverse(route),wait_until='networkidle')
                self.assertEqual(page.locator('[data-site-guide-start]').count(),0,route)
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page.goto(self.live_server_url+reverse('my_payments'),wait_until='networkidle')
            page.locator('[data-site-guide-start]').filter(visible=True).first.click()
            expect(page.locator('[data-guide-panel]')).to_be_visible()
            page.evaluate('document.dispatchEvent(new CustomEvent("account:unmounting"))')
            expect(page.locator('[data-guide-panel]')).to_be_hidden()
            page.locator('[data-account-key="my_profile"]').click()
            page.wait_for_function('Boolean(window.AccountNavigation) && !window.AccountNavigation.navigating')
            self.assertEqual(page.locator('[data-site-guide-start]').count(),0)

    def test_actual_feature_tours_and_responsive_screenshots(self):
        from playwright.sync_api import expect
        user=User.objects.create_user(username='tour-pages',email='pages@example.com',role='customer',email_verified=True)
        booking=Booking.objects.create(user=user,event_type='Birthday',event_date=timezone.localdate()+timedelta(days=80),event_time=time(9),event_end_time=time(11),event_location='Sample Function Hall, Bacoor',package_type='Package 1-A',total_price=10000,status='pending_payment',approved_at=timezone.now(),payment_due_at=timezone.now()+timedelta(days=2))
        self.client.force_login(user)
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check/site-guide/spotlight'
        artifacts.mkdir(parents=True,exist_ok=True)
        with self.browser_context(viewport={'width':1440,'height':1000},reduced_motion='reduce') as context:
            def assets(route):
                url=route.request.url
                if url.startswith(self.live_server_url+'/'):return route.continue_()
                for marker,name in {'fabric.min.js':'fabric-5.3.1.js','fullcalendar@6.1.11/index.global.min.js':'fullcalendar-6.1.11.js','leaflet.js':'leaflet.js','sweetalert2@11':'sweetalert2.all.min.js'}.items():
                    if marker in url:
                        path=Path(settings.BASE_DIR)/'.booking-followup-check'/name
                        if not path.exists():return route.continue_()
                        body=path.read_text(encoding='utf-8')
                        if marker=='fabric.min.js':body+=';fabric.Canvas=new Proxy(fabric.Canvas,{construct(Target,args){const instance=Reflect.construct(Target,args);window.tourTestCanvas=instance;return instance;}});'
                        return route.fulfill(content_type='application/javascript',body=body)
                return route.abort()
            context.route('**/*',assets)
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page();errors=[];style_issues=[]
            page.on('pageerror',lambda error:errors.append(str(error)))

            def check_tour(name,launcher,minimum_steps=2):
                launcher.scroll_into_view_if_needed()
                page.mouse.move(0,0)
                page.wait_for_function("[...document.getAnimations()].every(animation=>animation.playState!=='running' || animation.effect.getComputedTiming().iterations===Infinity)")
                minimum_height=36 if launcher.evaluate("button=>Boolean(button.closest('.site-guide-canvas-desktop,.site-guide-header-actions,.site-guide-dialog-head,.site-guide-dialog-tools,.stepper-header'))") else 44
                button_box=launcher.bounding_box();self.assertGreaterEqual(button_box['height'],minimum_height)
                modal_launcher=launcher.evaluate("button=>Boolean(button.closest('dialog,[role=dialog],#bookingModalOverlay,#editBookingModal'))")
                expected_border='0px' if modal_launcher else '1px'
                self.assertEqual(launcher.evaluate('button=>getComputedStyle(button).borderTopWidth'),expected_border,name)
                if launcher.evaluate("button=>Boolean(button.closest('.site-guide-header-actions'))"):
                    legend_box=page.locator('.site-guide-header-actions .legend-item').bounding_box()
                    self.assertAlmostEqual(button_box['height'],legend_box['height'],delta=1,msg=name)
                    self.assertAlmostEqual(button_box['y'],legend_box['y'],delta=1,msg=name)
                self.assertGreaterEqual(button_box['x'],0)
                self.assertLessEqual(button_box['x']+button_box['width'],page.viewport_size['width'])
                self.assertFalse(launcher.evaluate('''button => {
                    const header=button.closest('header,.stepper-header,.panel-header,.pu-head,.account-page-header');
                    if(!header)return false;
                    const a=button.getBoundingClientRect();
                    return [...header.querySelectorAll('button,a.pu-back,.stepper-wrapper')].some(other=>{
                        if(other===button || !other.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))return false;
                        const b=other.getBoundingClientRect();
                        return a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top;
                    });
                }'''),name)
                alignment=launcher.evaluate('''button => {
                    const header=button.closest('header,.stepper-header,.cp-modal-header');
                    const other=header?.querySelector(':scope>button:last-child');
                    if(!other || other===button)return null;
                    const a=button.getBoundingClientRect(),b=other.getBoundingClientRect();
                    return Math.abs(a.y+a.height/2-b.y-b.height/2);
                }''')
                if alignment is not None and alignment>1:style_issues.append(f'{name}: controls differ by {alignment:.1f}px')
                resting_background=launcher.evaluate('button=>getComputedStyle(button).backgroundColor')
                page.screenshot(path=str(artifacts/f'{name}-launcher.png'))
                launcher.hover()
                page.wait_for_function("[...document.getAnimations()].every(animation=>animation.playState!=='running' || animation.effect.getComputedTiming().iterations===Infinity)")
                if page.evaluate("matchMedia('(hover:hover) and (pointer:fine)').matches") and launcher.evaluate('button=>getComputedStyle(button).backgroundColor')==resting_background:
                    style_issues.append(f'{name}: no background hover feedback')
                self.assertEqual(launcher.evaluate('button=>getComputedStyle(button).borderTopWidth'),expected_border,name)
                page.screenshot(path=str(artifacts/f'{name}-launcher-hover.png'))
                launcher.click();panel=page.locator('[data-guide-panel]');expect(panel).to_be_visible()
                seen=[]
                for number in range(12):
                    seen.append(page.locator('[data-guide-title]').inner_text())
                    box=panel.bounding_box();viewport=page.viewport_size
                    self.assertGreaterEqual(box['x'],0);self.assertGreaterEqual(box['y'],0)
                    self.assertLessEqual(box['x']+box['width'],viewport['width']);self.assertLessEqual(box['y']+box['height'],viewport['height'])
                    if number<2:page.screenshot(path=str(artifacts/f'{name}-{number+1}.png'))
                    button=page.locator('[data-guide-next]')
                    if button.inner_text()=='Done':button.click();break
                    button.click()
                expect(panel).to_be_hidden()
                self.assertGreaterEqual(len(seen),minimum_steps,name)
                return seen

            page.goto(self.live_server_url+reverse('booking_page'),wait_until='networkidle')
            for theme in ('light','dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                for width,height in ((1440,1000),(768,900),(390,844),(320,568)):
                    page.set_viewport_size({'width':width,'height':height})
                    seen=check_tour(f'calendar-{theme}-{width}',page.locator('.panel-header [data-site-guide-start]'))
                    self.assertIn('Calendar controls',seen)
            day=(timezone.localdate()+timedelta(days=40)).isoformat()
            page.goto(self.live_server_url+reverse('booking_page')+'?from=estimate&event_date='+day,wait_until='networkidle')
            for theme in ('light','dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                for width,height in ((1440,1000),(390,844),(320,568)):
                    page.set_viewport_size({'width':width,'height':height})
                    seen=check_tour(f'booking-form-{theme}-{width}',page.locator('#bookingModalOverlay [data-site-guide-start]'))
                    self.assertIn('Booking sections',seen)
            self.assertEqual(page.locator('#event_type_select').input_value(),'')
            page.goto(self.live_server_url+reverse('customer_profile'),wait_until='networkidle')
            for width,height in ((1440,1000),(390,844),(320,568)):
                page.set_viewport_size({'width':width,'height':height})
                check_tour(f'bookings-{width}',page.locator('.account-page-header [data-site-guide-start]'))
            for width,height in ((1440,1000),(390,844),(320,568)):
                page.set_viewport_size({'width':width,'height':height})
                for modal_id,open_function,close_name in (
                    ('bookingModal','openBookingModal','Close booking details'),
                    ('eventDesignModal','openEventDesignModal','Close event design'),
                ):
                    page.evaluate('(args)=>window[args.name](args.id)',{'name':open_function,'id':booking.pk})
                    expect(page.locator(f'#{modal_id}')).to_be_visible()
                    check_tour(f'{modal_id}-{width}',page.locator(f'#{modal_id} [data-site-guide-start]'))
                    page.get_by_role('button',name=close_name,exact=True).click()
                    expect(page.locator(f'#{modal_id}')).to_be_hidden()
                page.evaluate('window.CustomerBookingModals.activateExisting("editBookingModal")')
                check_tour(f'edit-booking-{width}',page.locator('#editBookingModal [data-site-guide-start]'))
                page.get_by_role('button',name='Close edit booking form',exact=True).click()
            page.goto(self.live_server_url+reverse('design_canvas')+'?custom=true',wait_until='networkidle')
            page.wait_for_function('Boolean(window.fabric)')
            for width,height in ((1440,1000),(390,844),(320,568)):
                page.set_viewport_size({'width':width,'height':height})
                if width<1025:
                    page.locator('#mobileCanvasToolsBtn').click();launcher=page.locator('#mobileCanvasToolsDialog [data-site-guide-start]')
                else:launcher=page.locator('.site-guide-canvas-desktop [data-site-guide-start]')
                seen=check_tour(f'canvas-{width}',launcher)
                self.assertIn('Design tools',seen)
                self.assertIn('Saved layouts',seen)
            for panel_id in ('elementsPanel','textPanel','uploadsPanel','layersPanel'):
                page.locator(f'.canvas-tool-rail [data-panel-target="{panel_id}"]').click()
                check_tour(f'canvas-{panel_id}-320',page.locator('#mobileInventoryDialog [data-site-guide-start]'),minimum_steps=1)
                page.locator('#mobileInventoryDialog [data-mobile-close]').click()
            page.locator('#mobileChecklistBtn').click()
            check_tour('canvas-checklist-320',page.locator('#mobileChecklistDialog [data-site-guide-start]'))
            page.locator('#mobileChecklistDialog [data-mobile-close]').click()
            page.set_viewport_size({'width':1440,'height':1000})
            page.evaluate('''() => {
                const canvas=window.tourTestCanvas;
                const object=new fabric.Rect({width:70,height:70,left:180,top:160,fill:'#888'});
                canvas.add(object);canvas.setActiveObject(object);canvas.renderAll();
                window.tourObject=object;
            }''')
            original=page.evaluate('({count:tourTestCanvas.getObjects().length,left:tourObject.left,top:tourObject.top})')
            page.locator('.site-guide-canvas-desktop [data-site-guide-start]').click()
            for key in ('Delete','Backspace','ArrowRight','ArrowDown','Control+d','Control+z'):
                page.keyboard.press(key)
            self.assertEqual(page.evaluate('({count:tourTestCanvas.getObjects().length,left:tourObject.left,top:tourObject.top})'),original)
            page.get_by_role('button',name='Next',exact=True).press('Space')
            expect(page.locator('[data-guide-progress]')).to_have_text('2 of 5')
            page.keyboard.press('Escape')
            expect(page.locator('[data-guide-panel]')).to_be_hidden()
            page.locator('#saveDesignBtn').click()
            expect(page.locator('#saveDesignModal')).to_be_visible()
            check_tour('save-design-dialog',page.locator('#saveDesignModal [data-site-guide-start]'))
            page.locator('#saveDesignCancelBtn').click()
            page.goto(self.live_server_url+reverse('my_payments'),wait_until='networkidle')
            for width,height in ((1440,1000),(390,844)):
                page.set_viewport_size({'width':width,'height':height})
                seen=check_tour(f'payments-{width}',page.locator('.pu-head [data-site-guide-start]'))
                self.assertIn('Payment categories',seen)
            for theme in ('light','dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                for width,height in ((1440,1000),(390,844),(320,568)):
                    page.set_viewport_size({'width':width,'height':height})
                    page.locator('.cp-tab-panel.is-active .cp-btn-view').first.click()
                    expect(page.locator('#bookingModal')).to_be_visible()
                    check_tour(f'payment-details-{theme}-{width}',page.locator('#bookingModal [data-site-guide-start]'))
                    page.get_by_role('button',name='Close payment details',exact=True).click()
            page.goto(self.live_server_url+reverse('payment_page',args=[booking.pk]),wait_until='networkidle')
            for width,height in ((1440,1000),(390,844)):
                page.set_viewport_size({'width':width,'height':height})
                seen=check_tour(f'checkout-{width}',page.locator('.pu-head [data-site-guide-start]'))
                self.assertIn('Payment options',seen)
            self.assertFalse(page.locator('#js-refund-ack').is_checked())
            with context.browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True,reduced_motion='reduce') as touch_context:
                touch_context.route('**/*',assets)
                touch_context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
                page=touch_context.new_page()
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(self.live_server_url+reverse('booking_page')+'?from=estimate&event_date='+day,wait_until='networkidle')
                launcher=page.locator('#bookingModalOverlay [data-site-guide-start]')
                check_tour('booking-form-touch',launcher)
                self.assertGreaterEqual(launcher.bounding_box()['height'],44)
                self.assertGreaterEqual(page.locator('#closeModalBtn').bounding_box()['height'],44)
                page.locator('#closeModalBtn').click()
                check_tour('calendar-touch',page.locator('.panel-header [data-site-guide-start]'))
                page.goto(self.live_server_url+reverse('my_payments'),wait_until='networkidle')
                page.locator('.cp-tab-panel.is-active .cp-btn-view').first.click()
                check_tour('payment-details-touch',page.locator('#bookingModal [data-site-guide-start]'))
                self.assertGreaterEqual(page.locator('#bookingModal [data-site-guide-start]').bounding_box()['height'],44)
            self.assertEqual(style_issues,[], '\n'.join(style_issues))
            self.assertEqual(errors,[])

    def test_custom_booking_modal_guide_does_not_close_the_form_or_apply_actions(self):
        from playwright.sync_api import expect
        user=User.objects.create_user(username='tour-modal',email='modal@example.com',role='customer',email_verified=True)
        self.client.force_login(user)
        with self.browser_context(viewport={'width':1280,'height':900},reduced_motion='reduce') as context:
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page();page.goto(self.live_server_url+reverse('customer_profile'),wait_until='networkidle')
            page.evaluate('window.CustomerBookingModals.activateExisting("editBookingModal")')
            modal=page.locator('#editBookingModal');launcher=modal.locator('[data-site-guide-start]');launcher.click()
            expect(page.locator('[data-guide-panel]')).to_be_visible()
            page.get_by_role('button',name='Next',exact=True).click()
            page.keyboard.press('Escape')
            expect(page.locator('[data-guide-panel]')).to_be_hidden();expect(modal).to_be_visible()
            expect(launcher).to_be_focused()
            self.assertEqual(page.locator('#edit_event_type_select').input_value(),'')
