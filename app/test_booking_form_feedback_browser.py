import os
from contextlib import contextmanager
from pathlib import Path
from unittest import skipUnless
from urllib.request import urlopen

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .test_booking_change_feedback import feedback_booking
from .test_booking_preview import _preview_upload


@skipUnless(os.environ.get('RUN_BOOKING_FORM_FEEDBACK_BROWSER') == '1', 'Optional Playwright verification')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies', SESSION_COOKIE_SECURE=False,
                   CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False, REQUEST_RATE_LIMITING_ENABLED=False)
class BookingFormFeedbackBrowserTests(StaticLiveServerTestCase):
    def test_request_banner_enters_before_step_content_and_respects_reduced_motion(self):
        with self.browser_page() as page:
            self.open_form(page,'request')
            motion=page.locator('#changeRequestBanner').evaluate('''el=>{
                const banner=getComputedStyle(el),step=getComputedStyle(document.getElementById('edit-step-1'));
                return {name:banner.animationName,duration:parseFloat(banner.animationDuration),
                    delay:parseFloat(banner.animationDelay),stepDelay:parseFloat(step.animationDelay)};
            }''')
            self.assertEqual(motion['name'],'fadeInUp')
            self.assertGreater(motion['duration'],0)
            self.assertGreater(motion['stepDelay'],motion['delay'])
            for button in ['btnNextEditToSummary','btnNextEditStep','btnNextEditDesignToReview',
                           'btnPrevEditToDetails','btnPrevFromEditDesign','btnEditPackagesBack']:
                page.evaluate('()=>{window.previousBannerAnimation=document.getElementById("changeRequestBanner").getAnimations()[0];}')
                page.locator('#'+button).click()
                self.assertTrue(page.locator('#changeRequestBanner').evaluate(
                    'el=>el.getAnimations().length>0 && el.getAnimations()[0]!==window.previousBannerAnimation'))
            page.emulate_media(reduced_motion='reduce')
            self.assertEqual(page.locator('#changeRequestBanner').evaluate('el=>getComputedStyle(el).animationName'),'none')

    @contextmanager
    def browser_page(self, maps=False):
        from playwright.sync_api import sync_playwright
        user, self.booking, payment = feedback_booking()
        self.pending = type(self.booking).objects.get(pk=self.booking.pk)
        self.pending.pk = None
        self.pending.status = 'pending'
        self.pending.save()
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='no-preference')
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.live_server_url+'/') else route.abort())
            if maps:
                cache = Path(settings.BASE_DIR)/'.booking-followup-check/review-map'
                cache.mkdir(parents=True, exist_ok=True)
                for filename in ('leaflet.js','leaflet.css'):
                    asset = cache/filename
                    if not asset.exists():
                        asset.write_bytes(urlopen('https://unpkg.com/leaflet@1.9.4/dist/'+filename,timeout=30).read())
                    context.route('**/leaflet@1.9.4/dist/'+filename, lambda route, request, asset=asset: route.fulfill(
                        content_type='text/css' if asset.suffix=='.css' else 'application/javascript',body=asset.read_bytes()))
                context.route('**/MapServer/tile/**', lambda route: route.fulfill(content_type='image/png',body=_preview_upload().read()))
                context.route('**/reverse/**', lambda route: route.fulfill(json={'results':[{'display_name':'Test Venue, Bacoor, Cavite, Philippines'}]}))
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page = context.new_page()
            page.set_default_timeout(10000)
            try:
                yield page
            finally:
                context.close()
                browser.close()

    def open_form(self, page, mode):
        if mode=='create':
            page.goto(self.live_server_url+reverse('booking_page')+'?from=estimate&event_date=2099-07-17',wait_until='networkidle')
        else:
            page.goto(self.live_server_url+reverse('customer_profile')+(f'?open_edit={self.pending.pk}' if mode=='edit' else ''),wait_until='networkidle')
            if mode=='request':
                page.get_by_role('button',name='Request Changes',exact=True).click()
                dialog=page.locator('dialog.client-feedback-dialog')
                dialog.get_by_role('textbox').fill('We need to change some event preferences.')
                dialog.get_by_role('button',name='Continue to Changes').click()

    def test_required_event_and_design_fields_scroll_and_focus_consistently(self):
        from playwright.sync_api import expect
        with self.browser_page() as page:
            for mode in ('create','edit','request'):
                self.open_form(page,mode)
                edit=mode!='create'
                prefix='edit_' if edit else ''
                if not edit:
                    page.locator('#eventTypeCustomSelect .custom-select-trigger').click()
                    page.locator('#eventTypeCustomSelect [data-value="Birthday"]').click()
                page.evaluate('''prefix => {
                    for(const [name,value] of Object.entries({event_date:'2099-07-17',start_time:'',end_time:'10:00',event_location:'Molino Bacoor Cavite venue'})){
                        const input=document.getElementById(prefix+name);input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));
                    }
                    window.scrollCalls=[];
                    const original=Element.prototype.scrollIntoView;
                    Element.prototype.scrollIntoView=function(options){scrollCalls.push({id:this.id,options});return original.call(this,options);};
                }''',prefix)
                page.locator('#btnNextEditToSummary' if edit else '#btnNextToSummary').click()
                expect(page.locator('#'+prefix+'start_time_display')).to_be_focused()
                self.assertEqual(page.evaluate('scrollCalls.at(-1).options.behavior'),'smooth')
                page.evaluate('prefix => {const el=document.getElementById(prefix+"start_time");el.value="07:00";el.dispatchEvent(new Event("change",{bubbles:true}));}',prefix)
                page.locator('#btnNextEditToSummary' if edit else '#btnNextToSummary').click()
                if not edit:
                    page.locator('.package-card[data-package="Package 2"] .package-info').click()
                page.locator('#btnNextEditStep' if edit else '#btnNextStep').click()
                if edit:
                    page.locator('#editDesignThemeChips .design-chip.selected').click()
                else:
                    page.evaluate('prefix => {document.getElementById(prefix+"design_theme_input").value="";}',prefix)
                page.locator('#btnNextEditDesignToReview' if edit else '#btnNextDesignToReview').click()
                group=page.locator('#editDesignThemeChips' if edit else '#designThemeChips')
                expect(group).to_be_focused()
                self.assertEqual(page.evaluate('scrollCalls.at(-1).options.behavior'),'smooth')
                group.locator('[data-value="Princess"]').click()
                page.evaluate('prefix => {document.getElementById(prefix+"color_palette_input").value="";}',prefix)
                page.emulate_media(reduced_motion='reduce')
                page.locator('#btnNextEditDesignToReview' if edit else '#btnNextDesignToReview').click()
                expect(page.locator('#editDesignPaletteSwatches' if edit else '#designPaletteSwatches')).to_be_focused()
                self.assertEqual(page.evaluate('scrollCalls.at(-1).options.behavior'),'auto')
                page.emulate_media(reduced_motion='no-preference')

    def test_map_status_colors_survive_light_and_dark_themes(self):
        from playwright.sync_api import expect
        with self.browser_page(maps=True) as page:
            for mode in ('create','edit','request'):
                self.open_form(page,mode)
                prefix='' if mode=='create' else 'edit_'
                for theme in ('light','dark'):
                    page.evaluate('theme => document.documentElement.dataset.theme=theme',theme)
                    page.locator('#'+prefix+'event_location').fill('Find a different venue '+theme)
                    chip=page.locator('#'+prefix+'booking_pin_status')
                    expect(chip).to_contain_text('No pin yet')
                    error=chip.evaluate('el=>getComputedStyle(el).color')
                    page.locator('#btnNextEditToSummary' if prefix else '#btnNextToSummary').click()
                    status=page.locator('#'+prefix+'location_map_status')
                    expect(status).to_have_class('location-map-status is-error')
                    self.assertEqual(status.evaluate('el=>getComputedStyle(el).color'),error)
                    page.evaluate('''() => {navigator.geolocation.getCurrentPosition=(success,error)=>{window.finishLocation=success;};}''')
                    page.locator('#'+('edit_location_use_my' if prefix else 'location_use_my')).click()
                    expect(status).to_contain_text('Finding your current location')
                    loading=status.evaluate('el=>getComputedStyle(el).color')
                    muted=status.evaluate('el=>getComputedStyle(el).getPropertyValue("--form-muted").trim()')
                    expected=page.evaluate('color=>{const el=document.createElement("span");el.style.color=color;document.body.append(el);const rgb=getComputedStyle(el).color;el.remove();return rgb;}',muted)
                    self.assertEqual(loading,expected)
                    page.evaluate('()=>finishLocation({coords:{latitude:14.414,longitude:120.982}})')
                    expect(status).to_contain_text('Location pinned.')
                    success=status.evaluate('el=>getComputedStyle(el).color')
                    self.assertNotEqual(error,success)
                    self.assertNotEqual(loading,success)
                    self.assertNotEqual(error,loading)
