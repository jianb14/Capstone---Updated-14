"""Theme state, snapshot transitions, fallback and responsive avatar controls."""
import os
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from .models import User


@skipUnless(os.environ.get('RUN_THEME_CONTROLS_BROWSER')=='1','Optional browser verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class ThemeControlsBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        user=User.objects.create_user(username='theme-controls',first_name='Jamie',last_name='Rivera',
            email='theme@example.com',role='customer',email_verified=True)
        self.client.force_login(user)
        self.cookie={'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}
        self.artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'
        self.artifacts.mkdir(exist_ok=True)

    def test_reveal_icons_rapid_clicks_persistence_and_mobile_avatar(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='no-preference')
            context.add_cookies([self.cookie])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            context.add_init_script('''
                if (!localStorage.getItem('balloorina-theme')) localStorage.setItem('balloorina-theme','light');
                window.themeReveals=[];
                const themeAnimate=Element.prototype.animate;
                Element.prototype.animate=function(frames,options) {
                    const animation=themeAnimate.call(this,frames,options);
                    if(options?.id==='theme-reveal') window.themeReveals.push({frames,pseudo:options.pseudoElement});
                    return animation;
                };
            ''')
            page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            root=page.locator('html')
            button=page.locator('.profile-dropdown > .theme-toggle-btn')
            def settled(theme):
                page.wait_for_function('!document.documentElement.classList.contains("theme-revealing") && !document.documentElement.classList.contains("theme-animating")')
                self.assertEqual(page.evaluate('document.documentElement.dataset.theme || "dark"'),theme)
                self.assertEqual(page.evaluate('localStorage.getItem("balloorina-theme")'),theme)
            try:
                page.goto(self.live_server_url+reverse('report_concern'),wait_until='domcontentloaded')
                page.locator('#subject').fill('Keep this report while switching themes')
                expect(button).to_have_attribute('aria-label','Switch to dark mode')
                expect(button.locator('.theme-icon-moon')).to_be_visible()
                before=button.bounding_box()
                button.click()
                page.wait_for_function('window.themeReveals.length===1')
                reveal=page.evaluate('window.themeReveals[0]')
                self.assertEqual(reveal['pseudo'],'::view-transition-new(root)')
                origin=re.search(r'at ([\d.]+)px ([\d.]+)px',reveal['frames'][0]['clipPath'])
                self.assertIsNotNone(origin)
                self.assertAlmostEqual(float(origin.group(1)),before['x']+before['width']/2,delta=.5)
                self.assertAlmostEqual(float(origin.group(2)),before['y']+before['height']/2,delta=.5)
                page.screenshot(path=str(self.artifacts/'theme-reveal-in-progress.png'))
                settled('dark')
                expect(button).to_have_attribute('aria-label','Switch to light mode')
                expect(button.locator('.theme-icon-sun')).to_be_visible()
                expect(button).to_be_focused()
                button.press('Enter')
                expect(root).to_have_attribute('data-theme','light')
                settled('light')
                page.evaluate('''() => { const button=document.querySelector('.profile-dropdown > .theme-toggle-btn');
                    for(let i=0;i<5;i++) window.toggleTheme(button); }''')
                page.wait_for_function('(document.documentElement.dataset.theme || "dark")==="dark"')
                settled('dark')
                expect(page.locator('#subject')).to_have_value('Keep this report while switching themes')
                self.assertEqual(len(documents),1)
                page.emulate_media(reduced_motion='reduce')
                count=page.evaluate('window.themeReveals.length')
                button.click()
                settled('light')
                self.assertEqual(page.evaluate('window.themeReveals.length'),count)
                for theme in ('light','dark'):
                    if page.evaluate('document.documentElement.dataset.theme || "dark"')!=theme:
                        button.click();settled(theme)
                    for width,height in ((1440,1000),(390,844),(320,568)):
                        page.set_viewport_size({'width':width,'height':height})
                        avatar=page.locator('.profile-avatar-btn .nav-avatar')
                        arrow=page.locator('.profile-avatar-chevron')
                        expect(arrow).to_be_visible()
                        a=avatar.bounding_box();c=arrow.bounding_box()
                        self.assertGreater(c['x'],a['x']+a['width']/2)
                        self.assertGreater(c['y'],a['y']+a['height']/2)
                        self.assertLess(c['x'],a['x']+a['width'])
                        self.assertLess(c['y'],a['y']+a['height'])
                        self.assertEqual(arrow.evaluate('(el)=>getComputedStyle(el).strokeWidth'),'1.5px')
                        page.locator('.profile-dropdown').screenshot(path=str(self.artifacts/f'theme-avatar-{theme}-{width}.png'),animations='disabled')
                    page.set_viewport_size({'width':1440,'height':1000})
                page.set_viewport_size({'width':390,'height':844})
                expect(button).to_be_hidden()
                page.locator('.mobile-menu').click()
                mobile=page.locator('.nav-links .theme-toggle-btn')
                expect(mobile).to_be_visible()
                mobile.click();settled('light')
                expect(page.locator('.nav-links')).to_have_class('nav-links nav-active')
                page.keyboard.press('Escape')
                page.reload(wait_until='domcontentloaded')
                settled('light')
                page.set_viewport_size({'width':1440,'height':1000})
                second=context.new_page()
                second.emulate_media(reduced_motion='reduce')
                second.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                second.locator('.profile-dropdown > .theme-toggle-btn').click()
                expect(root).not_to_have_attribute('data-theme','light')
                expect(button).to_have_attribute('aria-label','Switch to light mode')
                second.close()
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(self.artifacts/'theme-controls-failure.png'))
                raise
            finally:
                context.close();browser.close()

    def test_unavailable_view_transitions_and_blocked_storage_keep_toggle_usable(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1280,'height':900},reduced_motion='no-preference')
            context.add_cookies([self.cookie])
            context.add_init_script('''
                document.startViewTransition=undefined;
                const themeGet=Storage.prototype.getItem,themeSet=Storage.prototype.setItem;
                Storage.prototype.getItem=function(key){
                    if(key==='balloorina-theme') throw new DOMException('Blocked','SecurityError');
                    return themeGet.call(this,key);
                };
                Storage.prototype.setItem=function(key,value){
                    if(key==='balloorina-theme') throw new DOMException('Blocked','SecurityError');
                    return themeSet.call(this,key,value);
                };
            ''')
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                button=page.locator('.profile-dropdown > .theme-toggle-btn')
                expect(button).to_have_attribute('aria-label','Switch to light mode')
                button.click()
                expect(page.locator('html')).to_have_attribute('data-theme','light')
                page.wait_for_function('!document.documentElement.classList.contains("theme-animating")')
                expect(button).to_have_attribute('aria-label','Switch to dark mode')
                button.click()
                page.wait_for_function('!document.documentElement.classList.contains("theme-animating")')
                expect(button.locator('.theme-icon-sun')).to_be_visible()
                self.assertEqual(errors,[])
            finally:
                context.close();browser.close()
