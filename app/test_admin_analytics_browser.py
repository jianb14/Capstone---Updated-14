"""Opt-in real-browser checks for async reports, charts and responsive themes."""
import os
from datetime import timedelta, time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Payment, Review, User


@skipUnless(os.environ.get('RUN_ADMIN_ANALYTICS_BROWSER') == '1', 'Optional analytics browser verification')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminAnalyticsBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        admin = User.objects.create_user(username='report-browser-admin', role='admin', email_verified=True)
        customer = User.objects.create_user(username='report-browser-customer', role='customer', email_verified=True)
        today = timezone.localdate()
        for index, (day, status, event) in enumerate([(today,'completed','Birthday'), (today,'pending','Birthday'),
                (today,'cancelled','Wedding'), (today-timedelta(days=1),'completed','Wedding'),
                (today+timedelta(days=1),'confirmed','Birthday')]):
            booking = Booking.objects.create(user=customer, event_date=day, event_type=event,
                event_location='Venue', total_price=1000, status=status,event_time=time(9),
                package_type='Package 1-A + Entrance A + Stand A' if index < 3 else 'Entrance A (Solo)')
            if status == 'completed':
                Payment.objects.create(booking=booking, amount=500, payment_status='verified', received_at=timezone.now(), transaction_ref=f'BROWSER-REPORT-{index}')
                Review.objects.create(booking=booking,user=customer,rating=5,comment='Good experience')
        self.client.force_login(admin)
        self.url = self.live_server_url + reverse('admin_analytics')
        self.artifacts = Path(settings.BASE_DIR) / '.booking-followup-check'

    def context(self, playwright):
        browser = playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url':self.live_server_url}])
        context.add_init_script("localStorage.setItem('balloorina-theme','light')")
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://cdnjs.cloudflare.com/**', lambda route: route.abort())
        context.route('https://cdn.jsdelivr.net/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body='window.Swal={mixin:()=>({fire:()=>{}})};'))
        return browser, context

    def test_async_filters_comparisons_metrics_history_and_latest_response_wins(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.context(p); page = context.new_page(); errors=[]; documents=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url+'?filter_preset=today')
                total = page.locator('[data-kpi="bookings"] > strong')
                expect(total).to_have_text('3')
                page.wait_for_function('Object.keys(Chart.instances).length===4')
                page.get_by_role('button', name='Collections', exact=True).click()
                expect(page.locator('[data-trend="collections"]')).to_have_attribute('aria-pressed','true')
                self.assertEqual(page.evaluate('Chart.getChart(document.querySelector("[data-chart=trend]")).data.datasets[0].data'), [500])
                page.get_by_role('button', name='Event type: All event types').click()
                page.evaluate("document.dispatchEvent(new Event('scroll'))")
                page.get_by_role('option', name='Wedding', exact=True).click()
                expect(total).to_have_text('1')
                expect(page.locator('.ar-scope-label')).to_contain_text('Wedding')
                self.assertEqual(page.evaluate('Object.keys(Chart.instances).length'),4)
                page.go_back(); expect(total).to_have_text('3')
                page.get_by_role('button', name='Date basis: Event date', exact=True).click()
                page.get_by_role('option', name='Booking submission date', exact=True).click()
                expect(total).to_have_text('5')
                page.go_back(); expect(total).to_have_text('3')
                # Out-of-order delivery must never overwrite a newer filter selection.
                page.evaluate('''() => {
                  const original = window.fetch;
                  window.fetch = (...args) => original(...args).then(async response => {
                    if (String(args[0]).includes('filter_preset=today')) await new Promise(resolve=>setTimeout(resolve,350));
                    return response;
                  });
                  document.querySelector('[data-period=today]').click();
                  setTimeout(()=>document.querySelector('[data-period=all]').click(),50);
                }''')
                expect(total).to_have_text('5')
                page.wait_for_timeout(450)
                expect(total).to_have_text('5')
                expect(page.locator('[data-period="all"]')).to_have_attribute('aria-pressed','true')
                page.get_by_role('button', name='Today', exact=True).click(); expect(total).to_have_text('3')
                # Reversed dates keep the displayed results and show a validation message.
                page.get_by_label('From date').fill('2030-12-01')
                page.get_by_label('To date').fill('2020-01-01')
                page.get_by_role('button', name='Apply dates', exact=True).click()
                expect(page.locator('#analyticsError')).to_contain_text('cannot be after')
                expect(total).to_have_text('3')
                page.get_by_label('From date').fill('2040-01-01'); page.get_by_label('To date').fill('2040-01-02')
                page.get_by_role('button', name='Apply dates', exact=True).click()
                expect(total).to_have_text('0')
                expect(page.locator('.ar-chart-empty')).to_have_count(4)
                self.assertEqual(page.evaluate('Object.keys(Chart.instances).length'),0)
                page.get_by_role('button', name='Today', exact=True).click(); expect(total).to_have_text('3')
                self.assertEqual(page.evaluate('Object.keys(Chart.instances).length'),4)
                self.assertNotIn('filter_preset', page.locator('#analyticsExport').get_attribute('href'))
                self.assertEqual(len(documents),1)
                self.assertEqual(errors,[])
            finally: context.close(); browser.close()

    def test_responsive_themes_reduced_motion_and_network_error_keep_report(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser, context = self.context(p); page = context.new_page(); errors=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(self.url+'?filter_preset=today')
                page.wait_for_function('Object.keys(Chart.instances).length===4')
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    for width in (1440,768,390,320):
                        page.set_viewport_size({'width':width,'height':1000})
                        page.wait_for_timeout(300)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'Overflow at {width}/{theme}')
                        self.assertTrue(page.locator('[data-chart="trend"]').is_visible())
                        for canvas in page.locator('[data-chart]').all(): self.assertGreater(canvas.bounding_box()['width'],100)
                        page.screenshot(path=str(self.artifacts/f'admin-analytics-{theme}-{width}.png'), full_page=True, animations='disabled')
                    page.get_by_label('From date').focus()
                    self.assertEqual(page.get_by_label('From date').evaluate('(node)=>getComputedStyle(node).outlineStyle'),'solid')
                    self.assertNotEqual(page.get_by_label('From date').evaluate('(node)=>getComputedStyle(node).outlineColor'),'rgba(0, 0, 0, 0)')
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_function('Chart.getChart(document.querySelector("[data-chart=trend]")).options.animation.duration===0')
                self.assertEqual(page.locator('.ar-kpi').first.evaluate('(node)=>getComputedStyle(node).animationName'),'none')
                self.assertEqual(page.evaluate('Chart.getChart(document.querySelector("[data-chart=trend]")).options.animation.duration'),0)
                page.route('**/staff/analytics/?**', lambda route: route.abort() if route.request.resource_type=='fetch' else route.continue_())
                page.get_by_role('button', name='7 days', exact=True).click()
                expect(page.locator('#analyticsError')).to_be_visible()
                expect(page.locator('[data-kpi="bookings"] > strong')).to_have_text('3')
                expect(page.locator('#analyticsResults')).to_have_attribute('aria-busy','false')
                self.assertEqual(page.evaluate('Object.keys(Chart.instances).length'),4)
                self.assertEqual(errors,[])
            finally: context.close(); browser.close()

    def test_all_business_tabs_are_async_responsive_and_restore_history(self):
        from playwright.sync_api import expect, sync_playwright
        with sync_playwright() as p:
            browser,context=self.context(p);page=context.new_page();errors=[];documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            try:
                page.goto(self.url+'?filter_preset=today')
                for tab,count in [('bookings',6),('payments',3),('customers',2),('overview',4)]:
                    page.locator(f'[data-report-tab="{tab}"]').click()
                    expect(page.locator(f'[data-report-view="{tab}"]')).to_be_visible()
                    page.wait_for_function('(count)=>Object.keys(Chart.instances).length===count',arg=count)
                    for theme in ('light','dark'):
                        page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                        for width in (1920,1440,390,320):
                            page.set_viewport_size({'width':width,'height':1000})
                            page.wait_for_timeout(170)
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),f'{tab}/{theme}/{width}')
                            if width>=1440:
                                grid=page.locator('.ar-kpis').evaluate('(node)=>({columns:getComputedStyle(node).gridTemplateColumns.split(" ").length,rows:getComputedStyle(node).gridTemplateRows.split(" ").length})')
                                self.assertEqual(grid,{'columns':3,'rows':2})
                            for canvas in page.locator('[data-chart]').all():self.assertGreater(canvas.bounding_box()['width'],100)
                            if width in (1440,390):page.screenshot(path=str(self.artifacts/f'analytics-{tab}-{theme}-{width}.png'),full_page=True,animations='disabled')
                page.go_back();expect(page.locator('[data-report-view="customers"]')).to_be_visible()
                expect(page.locator('[data-kpi="returning_customers"] > strong')).to_have_text('1')
                page.go_back();expect(page.locator('[data-report-view="payments"]')).to_be_visible()
                expect(page.locator('[data-kpi="received"] > strong')).to_have_text('₱1,000.00')
                # Tabs use the applied report, rather than unsubmitted date drafts.
                page.get_by_label('From date').fill('2040-01-01')
                page.locator('[data-report-tab="bookings"]').click()
                expect(page.locator('[data-kpi="bookings"] > strong')).to_have_text('3')
                expect(page.get_by_label('From date')).not_to_have_value('2040-01-01')
                page.locator('[data-report-tab="customers"]').focus();page.keyboard.press('Enter')
                expect(page.locator('[data-report-view="customers"]')).to_be_visible()
                page.get_by_label('From date').fill('2040-01-01');page.get_by_label('To date').fill('2040-01-02')
                page.get_by_role('button',name='Apply dates',exact=True).click()
                expect(page.locator('.ar-chart-empty')).to_have_count(2)
                expect(page.locator('[data-kpi="average_rating"] > strong')).to_have_text('—')
                # Reset restores dates while retaining the applied view and filters.
                page.get_by_role('button',name='Date basis: Event date',exact=True).click()
                page.get_by_role('option',name='Booking submission date',exact=True).click()
                expect(page.locator('.ar-scope-label')).to_contain_text('Booking submission date')
                page.get_by_role('button',name='Event type: All event types',exact=True).click()
                page.get_by_role('option',name='Wedding',exact=True).click()
                expect(page.locator('.ar-scope-label')).to_contain_text('Wedding')
                page.get_by_label('From date').fill('2050-01-01')
                page.get_by_role('link',name='Reset',exact=True).click()
                expect(page.locator('[data-period="30days"]')).to_have_attribute('aria-pressed','true')
                expect(page.get_by_label('From date')).to_have_value((timezone.localdate()-timedelta(days=29)).isoformat())
                expect(page.get_by_label('To date')).to_have_value(timezone.localdate().isoformat())
                expect(page.locator('[data-report-view="customers"]')).to_be_visible()
                expect(page.locator('.ar-scope-label')).to_contain_text('Booking submission date')
                expect(page.locator('.ar-scope-label')).to_contain_text('Wedding')
                expect(page.locator('#analyticsError')).to_be_hidden()
                self.assertIn('date_basis=created',page.locator('#analyticsExport').get_attribute('href'))
                self.assertIn('event_type=Wedding',page.locator('#analyticsExcel').get_attribute('href'))
                self.assertEqual(len(documents),1)
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_compact_columns_full_width_chart_theme_emphasis_and_animated_filter_update(self):
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.context(p);page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.url+'?filter_preset=today')
                page.wait_for_function('Object.keys(Chart.instances).length===4')
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_timeout(120)
                boxes=page.locator('.ar-chart-card').evaluate_all('(cards)=>cards.map(card=>{const r=card.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})')
                self.assertAlmostEqual(boxes[3]['y'],boxes[1]['y']+boxes[1]['height']+18,delta=3)
                self.assertLess(boxes[3]['y'],boxes[2]['y'])
                for theme in ('light','dark'):
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value',theme)
                    strong=page.locator('.ar-definitions strong').first
                    color=strong.evaluate('(node)=>getComputedStyle(node).color')
                    muted=page.locator('.ar-definitions p').first.evaluate('(node)=>getComputedStyle(node).color')
                    self.assertNotEqual(color,muted)
                    self.assertGreaterEqual(int(strong.evaluate('(node)=>getComputedStyle(node).fontWeight')),500)
                page.emulate_media(reduced_motion='no-preference')
                identity=page.locator('[data-chart="trend"]').evaluate('(canvas)=>Chart.getChart(canvas).id')
                page.get_by_role('button',name='Event type: All event types').click()
                page.get_by_role('option',name='Wedding',exact=True).click()
                expect(page.locator('[data-kpi="bookings"] > strong')).to_have_text('1')
                self.assertEqual(identity,page.locator('[data-chart="trend"]').evaluate('(canvas)=>Chart.getChart(canvas).id'))
                self.assertEqual(page.locator('[data-chart="trend"]').evaluate('(canvas)=>Chart.getChart(canvas).options.animation.duration'),620)
                self.assertEqual(page.locator('#analyticsResults').get_attribute('data-refresh'),'true')
                pdf=page.locator('#analyticsExport').get_attribute('href');excel=page.locator('#analyticsExcel').get_attribute('href')
                self.assertEqual(pdf.split('?')[1],excel.split('?')[1])
                page.locator('[data-report-tab="bookings"]').click()
                expect(page.locator('[data-report-view="bookings"]')).to_be_visible()
                page.emulate_media(reduced_motion='reduce');page.wait_for_timeout(120)
                offers=page.locator('.ar-chart-grid').nth(1)
                box=offers.bounding_box();last=offers.locator('.ar-chart-card').last.bounding_box()
                self.assertAlmostEqual(box['width'],last['width'],delta=2)
                self.assertLess(page.locator('[data-chart="stands"]').bounding_box()['height'],180)
                # Opening details recalculates the packing, keeping later cards clear.
                page.locator('[data-report-tab="overview"]').click()
                expect(page.locator('[data-report-view="overview"]')).to_be_visible()
                page.get_by_text('View trend data',exact=True).click()
                page.wait_for_timeout(120)
                first=page.locator('.ar-chart-card').nth(0).bounding_box();third=page.locator('.ar-chart-card').nth(2).bounding_box()
                self.assertGreaterEqual(third['y'],first['y']+first['height']+17)
                self.assertEqual(errors,[])
            finally:context.close();browser.close()

    def test_pdf_and_excel_download_the_applied_filter_without_page_navigation(self):
        import io
        import openpyxl
        from pypdf import PdfReader
        from playwright.sync_api import expect,sync_playwright
        with sync_playwright() as p:
            browser,context=self.context(p);page=context.new_page()
            try:
                page.goto(self.url+'?filter_preset=today')
                page.get_by_role('button',name='Event type: All event types').click()
                page.get_by_role('option',name='Wedding',exact=True).click()
                expect(page.locator('[data-kpi="bookings"] > strong')).to_have_text('1')
                url=page.url
                for label,suffix in [('Export PDF','.pdf'),('Export Excel','.xlsx')]:
                    with page.expect_download() as pending:page.get_by_role('link',name=label,exact=True).click()
                    download=pending.value
                    self.assertTrue(download.suggested_filename.endswith(suffix))
                    content=Path(download.path()).read_bytes()
                    if suffix=='.pdf':
                        text='\n'.join(sheet.extract_text() for sheet in PdfReader(io.BytesIO(content)).pages)
                        self.assertIn('Wedding',text);self.assertNotIn('Birthday',text)
                    else:
                        workbook=openpyxl.load_workbook(io.BytesIO(content))
                        self.assertEqual(workbook['Bookings Summary'].max_row,2)
                        self.assertEqual(workbook['Bookings Summary']['C2'].value,'Wedding')
                    self.assertEqual(page.url,url)
            finally:context.close();browser.close()
