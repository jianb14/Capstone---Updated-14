"""Opt-in complete settings form, public output and interrupted-save scenarios."""
import os
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from . import test_admin_configuration_browser as browser_fixture


@skipUnless(os.environ.get('RUN_CONFIGURATION_BROWSER')=='1','Optional settings browser checks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SiteSettingsFunctionalBrowserTests(StaticLiveServerTestCase):
    setUp=browser_fixture.AdminConfigurationBrowserTests.setUp
    browser=browser_fixture.AdminConfigurationBrowserTests.browser

    def test_every_section_saves_reloads_and_updates_the_public_website(self):
        from playwright.sync_api import sync_playwright,expect
        values={'ss_site_name':'Browser Updated Studio','ss_contact_email':'hello@browser.example',
            'ss_contact_phone':'+63 917 111 2222','ss_facebook':'https://www.facebook.com/browser-studio',
            'ss_instagram':'https://www.instagram.com/browser-studio/','ss_max_saved_designs':'25',
            'ss_lead_time':'5','ss_payment_window':'36','ss_design_lead':'48','ss_change_cutoff':'72',
            'ss_min_duration':'3','ss_included_hours':'4','ss_max_duration':'9','ss_overtime_rate':'750.50',
            'ss_admin_emails':'private-alerts@browser.example','ss_logistics_amount':'1400.00',
            'ss_logistics_free_radius_km':'30.00','ss_logistics_per_km_rate':'55.00','ss_logistics_max_fee_cap':'6000.00',
            'ss_logistics_notes':'Updated browser delivery notes.'}
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[]
            context.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',lambda route:route.fulfill(path=str(self.artifacts/'leaflet.js'),content_type='application/javascript'))
            context.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',lambda route:route.fulfill(path=str(self.artifacts/'leaflet.css'),content_type='text/css'))
            context.route('**'+reverse('booking_place_search')+'**',lambda route:route.fulfill(json={'results':[
                {'display_name':'Browser Studio, Tanza, Cavite','lat':14.414,'lon':120.982}]}))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                page.locator('#ss_address').fill('Browser Studio')
                page.get_by_role('option',name='Browser Studio, Tanza, Cavite',exact=True).click()
                expect(page.locator('#ss_shop_lat')).to_have_value('14.414')
                for field,value in values.items(): page.locator('#'+field).fill(value)
                page.locator('#ss_notif_toggle').uncheck()
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_feedback')).to_have_text('All site settings saved successfully.')
                expect(page.locator('.cfg-toast')).to_contain_text('All site settings saved successfully.')
                expect(page.locator('#ss_save_state')).to_have_text('Settings saved successfully')
                page.locator('.cfg-toast button').focus()
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for width in (1440,390):
                        page.set_viewport_size({'width':width,'height':950})
                        toast=page.locator('.cfg-toast')
                        self.assertTrue(toast.evaluate('''el=>{
                            const r=el.getBoundingClientRect();
                            return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight &&
                                el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
                        }'''))
                        page.screenshot(path=str(self.artifacts/f'settings-save-feedback-{theme}-{width}.png'),animations='disabled')
                page.locator('.cfg-toast').get_by_role('button',name='Dismiss notification').click()
                expect(page.locator('.cfg-toast')).to_be_hidden()
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                self.assertEqual(len(documents),1)
                public=context.new_page();public.on('pageerror',lambda error:errors.append(str(error)))
                public.goto(self.live_server_url+reverse('home'))
                expect(public).to_have_title('Browser Updated Studio | Balloon Styling & Event Design')
                footer=public.locator('.site-footer')
                expect(footer.get_by_text(values['ss_contact_email'],exact=True)).to_be_visible()
                expect(footer.get_by_text(values['ss_contact_phone'],exact=True)).to_be_visible()
                expect(footer.get_by_text('Browser Studio, Tanza, Cavite',exact=True)).to_be_visible()
                expect(footer.get_by_role('link',name='Facebook',exact=True)).to_have_attribute('href',values['ss_facebook'])
                expect(footer.get_by_role('link',name='Instagram',exact=True)).to_have_attribute('href',values['ss_instagram'])
                expect(public.get_by_text('private-alerts@browser.example',exact=True)).to_have_count(0)
                for theme in ('light','dark'):
                    public.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for width in (1440,390):
                        public.set_viewport_size({'width':width,'height':950})
                        footer.scroll_into_view_if_needed()
                        self.assertLessEqual(public.evaluate('document.documentElement.scrollWidth-innerWidth'),1)
                        public.screenshot(path=str(self.artifacts/f'site-settings-public-footer-{theme}-{width}.png'),animations='disabled')
                page.reload()
                for field,value in values.items():
                    if field == 'ss_admin_emails':
                        expect(page.locator('.cfg-email-tag>span')).to_have_text([value])
                        expect(page.locator('#ss_admin_emails')).to_have_value('')
                    else: expect(page.locator('#'+field)).to_have_value(value)
                expect(page.locator('#ss_address')).to_have_value('Browser Studio, Tanza, Cavite')
                expect(page.locator('#ss_shop_lat')).to_have_value('14.414')
                expect(page.locator('#ss_notif_toggle')).not_to_be_checked()
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_recipient_tags_validate_paste_remove_reset_and_save_without_reloading(self):
        from playwright.sync_api import sync_playwright,expect
        from .models import SiteSettings
        site=SiteSettings.load()
        site.admin_emails_for_notifications='original@example.com'
        site.save(update_fields=['admin_emails_for_notifications'])
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[];posts=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('request',lambda request:posts.append(request) if request.method=='POST' and request.url.endswith(reverse('admin_site_settings')) else None)
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                field=page.locator('#ss_admin_emails');tags=page.locator('.cfg-email-tag>span');save=page.locator('#ss_btn_save')
                expect(field).to_have_attribute('type','email')
                expect(tags).to_have_text(['original@example.com'])
                expect(save).to_be_disabled()
                field.fill('first@example.com');field.press('Enter')
                expect(tags).to_have_text(['original@example.com','first@example.com'])
                field.fill('FIRST@EXAMPLE.COM');field.press(',')
                expect(tags).to_have_count(2)
                field.evaluate(r'''el=>{
                    const data=new DataTransfer();data.setData('text','second@example.com\nthird@example.com;second@example.com');
                    el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,clipboardData:data}));
                }''')
                expect(tags).to_have_text(['original@example.com','first@example.com','second@example.com','third@example.com'])
                page.get_by_role('button',name='Remove second@example.com',exact=True).click()
                expect(tags).to_have_count(3)
                field.fill('not-an-email');save.click()
                expect(page.locator('#ss_admin_emails_error')).to_have_text('Enter a valid email address.')
                self.assertEqual(len(posts),0)
                expect(field).to_have_value('not-an-email')
                page.locator('#ss_reset').click()
                expect(tags).to_have_text(['original@example.com']);expect(field).to_have_value('')
                expect(page.locator('#ss_admin_emails_error')).to_be_empty();expect(save).to_be_disabled()
                # A valid pending address is included even without pressing Enter first.
                field.fill('pending@example.com');save.click()
                expect(page.locator('#ss_feedback')).to_have_text('All site settings saved successfully.')
                expect(tags).to_have_text(['original@example.com','pending@example.com']);expect(save).to_be_disabled()
                page.get_by_role('button',name='Remove original@example.com',exact=True).click()
                field.press('Backspace');expect(tags).to_have_count(0)
                page.locator('#ss_reset').click()
                expect(tags).to_have_text(['original@example.com','pending@example.com'])
                page.get_by_role('button',name='Remove original@example.com',exact=True).click()
                page.get_by_role('button',name='Remove pending@example.com',exact=True).click()
                save.click();expect(page.locator('#ss_feedback')).to_have_text('All site settings saved successfully.')
                expect(tags).to_have_count(0);expect(save).to_be_disabled()
                self.assertEqual(len(documents),1);self.assertEqual(len(posts),2);self.assertEqual(errors,[])
            finally:context.close();browser.close()
        self.assertEqual(SiteSettings.load().admin_emails_for_notifications,'')

    def test_settings_full_width_fields_recipient_wrap_and_savebar_gap_in_both_themes(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page()
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                field=page.locator('#ss_admin_emails')
                long_email='a'*60+'@'+('b'*55)+'.example.com'
                field.fill(long_email);field.press('Enter')
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for width in (1440,900,390,320):
                        page.set_viewport_size({'width':width,'height':950})
                        for selector in ('#ss_contact_phone','#ss_max_saved_designs'):
                            self.assertTrue(page.locator(selector).evaluate('''el=>{
                                const grid=el.closest('.cfg-field-grid');
                                return Math.abs(el.getBoundingClientRect().width-grid.getBoundingClientRect().width)<2;
                            }'''))
                        field.focus()
                        expect(page.locator('[data-email-recipients]')).to_have_css('outline-offset','2px')
                        expect(field).to_have_css('outline-style','none')
                        expect(page.locator('[data-email-recipients]')).not_to_have_css('outline-color','rgba(0, 0, 0, 0)')
                        self.assertLessEqual(page.locator('.cfg-workspace').evaluate('el=>el.scrollWidth-el.clientWidth'),1)
                        gap=page.locator('.cfg-savebar').evaluate('el=>innerHeight-el.getBoundingClientRect().bottom')
                        self.assertGreaterEqual(gap,15)
                        if width in (1440,390):
                            page.locator('#email-settings').scroll_into_view_if_needed()
                            page.screenshot(path=str(self.artifacts/f'site-settings-email-tags-{theme}-{width}.png'),animations='disabled')
                page.locator('#ss_reset').click()
            finally:context.close();browser.close()

    def test_failed_save_keeps_draft_allows_retry_and_session_error_stays_inline(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();errors=[];documents=[];requests=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            def save_route(route):
                if route.request.method!='POST': route.continue_();return
                requests.append(route.request)
                if len(requests)==1:route.abort('failed')
                elif len(requests)==2:route.fulfill(status=403,content_type='text/html',body='Session expired')
                elif len(requests)==3:route.fulfill(status=500,content_type='text/html',body='Temporarily unavailable')
                else:route.continue_()
            context.route('**'+reverse('admin_site_settings'),save_route)
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                page.locator('#ss_site_name').fill('Preserved draft')
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_feedback')).to_contain_text('Connection failed')
                expect(page.locator('.cfg-toast')).to_have_attribute('data-kind','error')
                expect(page.locator('.cfg-toast')).to_contain_text('Connection failed')
                expect(page.locator('#ss_site_name')).to_have_value('Preserved draft')
                expect(page.locator('#ss_btn_save')).to_be_enabled()
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_feedback')).to_contain_text('Your session may have expired')
                expect(page.locator('#ss_site_name')).to_have_value('Preserved draft')
                expect(page.locator('#ss_btn_save')).to_be_enabled()
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_feedback')).to_contain_text('Unable to save right now')
                expect(page.locator('#ss_site_name')).to_have_value('Preserved draft')
                expect(page.locator('#ss_btn_save')).to_be_enabled()
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_feedback')).to_have_text('All site settings saved successfully.')
                expect(page.locator('.cfg-toast')).to_have_attribute('data-kind','success')
                expect(page.locator('.cfg-toast')).to_contain_text('All site settings saved successfully.')
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                self.assertEqual(len(documents),1);self.assertEqual(len(requests),4);self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_changes_during_slow_save_remain_unsaved_and_duplicate_submit_is_ignored(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser,context=self.browser(p);page=context.new_page();posts=[]
            page.on('request',lambda request:posts.append(request) if request.method=='POST' and request.url.endswith(reverse('admin_site_settings')) else None)
            try:
                page.goto(self.live_server_url+reverse('admin_site_settings'))
                page.evaluate('''() => {
                    const original=window.fetch;let hold=true;
                    window.fetch=(...args)=>original(...args).then(response=>{
                        if(hold && args[1]?.method==='POST'){
                            hold=false;return new Promise(resolve=>window.releaseSavedResponse=()=>resolve(response));
                        }
                        return response;
                    });
                }''')
                page.locator('#ss_site_name').fill('First submitted name')
                page.locator('#ss_btn_save').click()
                page.wait_for_function('typeof window.releaseSavedResponse === "function"')
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                expect(page.locator('.cfg-toast')).to_be_hidden()
                page.locator('#ss_site_name').fill('New unsaved name')
                page.locator('#ss_form').evaluate('form=>form.requestSubmit()')
                self.assertEqual(len(posts),1)
                page.evaluate('window.releaseSavedResponse()')
                expect(page.locator('#ss_save_state')).to_have_text('You have unsaved changes')
                expect(page.locator('.cfg-toast')).to_contain_text('You still have unsaved changes.')
                expect(page.locator('#ss_site_name')).to_have_value('New unsaved name')
                expect(page.locator('#ss_btn_save')).to_be_enabled()
                persisted=context.new_page();persisted.goto(self.live_server_url+reverse('admin_site_settings'))
                expect(persisted.locator('#ss_site_name')).to_have_value('First submitted name')
                page.locator('#ss_btn_save').click()
                expect(page.locator('#ss_btn_save')).to_be_disabled()
                expect(page.locator('#ss_save_state')).to_have_text('Settings saved successfully')
                persisted.reload();expect(persisted.locator('#ss_site_name')).to_have_value('New unsaved name')
                self.assertEqual(len(posts),2)
            finally:context.close();browser.close()
