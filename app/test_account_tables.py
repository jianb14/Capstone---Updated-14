"""Account lists remain bounded, owner scoped and usable without a page reload."""
import os
import re
from datetime import timedelta
from pathlib import Path
from threading import Lock
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import ThreadedWSGIServer
from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.test.testcases import LiveServerThread
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingChangeRequest, ConcernTicket, Package, Payment, User


def account_fixture():
    user=User.objects.create_user(username='table-customer',email='tables@example.com',
        first_name='Jamie',last_name='Rivera',phone_number='09170000000',role='customer',email_verified=True)
    day=timezone.localdate()+timedelta(days=60)
    for i in range(18):
        booking=Booking.objects.create(user=user,event_type=f'Celebration {i:02}',event_date=day,
            event_location='Test venue',status='completed',total_price=100,package_type='Package 1-A')
        Payment.objects.create(booking=booking,amount=100,payment_status='verified',payment_method='gcash',
            transaction_ref=f'table-proof-{i:02}')
    for i in range(9):
        Booking.objects.create(user=user,event_type=f'Upcoming {i:02}',event_date=day,
            event_location='Test venue',status='pending_payment',total_price=100,package_type='Package 1-A')
        booking=Booking.objects.create(user=user,event_type=f'Balance {i:02}',event_date=day,
            event_location='Test venue',status='confirmed',total_price=100,package_type='Package 1-A')
        Payment.objects.create(booking=booking,amount=30,payment_status='verified',payment_method='gcash',
            transaction_ref=f'balance-proof-{i:02}')
    for i in range(21):
        ConcernTicket.objects.create(user=user,category='booking',subject=f'Concern {i:02}',message='Test message')
    return user


class AccountTableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=account_fixture()

    def setUp(self):
        self.client.force_login(self.user)

    def test_booking_pages_have_eight_rows_and_filter_links_preserve_query(self):
        url=reverse('customer_profile')
        first=self.client.get(url,{'sort_date':'id_asc','status':'completed','search':'Celebration'})
        second=self.client.get(url,{'page':2,'sort_date':'id_asc','status':'completed','search':'Celebration'})
        self.assertEqual(len(first.context['page_obj']),8)
        self.assertEqual(len(second.context['page_obj']),8)
        self.assertFalse(set(b.pk for b in first.context['page_obj']) & set(b.pk for b in second.context['page_obj']))
        self.assertContains(second,'Showing <strong>9–16</strong> of <strong>18</strong>',html=False)
        self.assertContains(second,'status=completed')
        self.assertContains(second,'search=Celebration')
        self.assertContains(first,'aria-label="Clear booking search"')

    def test_all_payment_queues_use_tables_and_independent_pagination(self):
        response=self.client.get(reverse('my_payments'))
        for key in ('action_required_page_obj','partial_page_obj','payments_page_obj'):
            self.assertEqual(len(response.context[key]),8,key)
        self.assertContains(response,'data-payment-row',count=24)
        self.assertNotContains(response,'class="mp-card ')
        self.assertContains(response,reverse('download_payment_receipt_pdf',args=[response.context['payments_page_obj'][0].pk]))
        second=self.client.get(reverse('my_payments'),{'tab':'payment_history','payments_page':2,'per_page':4,'status':'verified'})
        self.assertEqual(second.context['payments_page_obj'].number,2)
        self.assertEqual(len(second.context['payments_page_obj']),4)
        self.assertContains(second,'status=verified')

    def test_concern_pagination_reaches_older_tickets_and_embeds_current_page_details(self):
        response=self.client.get(reverse('report_concern'),{'page':3})
        page=response.context['tickets_page']
        self.assertEqual(page.paginator.count,21)
        self.assertEqual(len(page),5)
        self.assertEqual({ticket.pk for ticket in page},{ticket['id'] for ticket in response.context['ticket_data']})
        self.assertContains(response,'Concern 00')

    def test_invalid_sizes_cannot_return_more_than_eight_rows(self):
        for route,key in (('customer_profile','page_obj'),('my_payments','payments_page_obj'),('report_concern','tickets_page')):
            for value in ('0','-1','10000','all','bad'):
                response=self.client.get(reverse(route),{'per_page':value})
                self.assertEqual(len(response.context[key]),8,(route,value))
            response=self.client.get(reverse(route),{'per_page':4})
            self.assertEqual(len(response.context[key]),4)

    def test_booking_numeric_search_and_equal_date_sort_are_safe_and_stable(self):
        route=reverse('customer_profile')
        booking=Booking.objects.filter(user=self.user).first()
        response=self.client.get(route,{'search':f'#{booking.pk}'})
        self.assertEqual([item.pk for item in response.context['page_obj']],[booking.pk])
        for search in ('9'*100,'²','١٢٣'):
            self.assertEqual(self.client.get(route,{'search':search}).status_code,200)
        first=self.client.get(route,{'sort_date':'newest'}).context['page_obj']
        second=self.client.get(route,{'sort_date':'newest','page':2}).context['page_obj']
        self.assertFalse(set(item.pk for item in first)&set(item.pk for item in second))
        invalid=self.client.get(route,{'status':'invalid','sort_date':'invalid'})
        self.assertEqual(invalid.context['status_filter'],'all')
        self.assertEqual(invalid.context['sort_date'],'id_desc')

    def test_empty_and_filtered_lists_and_other_customers_stay_private(self):
        response=self.client.get(reverse('customer_profile'),{'search':'no-such-event'})
        self.assertEqual(len(response.context['page_obj']),0)
        self.assertContains(response,'No matching bookings')
        self.assertContains(response,'Showing <strong>0–0</strong>')
        stranger=User.objects.create_user(username='other-table-customer',role='customer',email_verified=True)
        self.client.force_login(stranger)
        for route,key in (('customer_profile','page_obj'),('my_payments','payments_page_obj'),('report_concern','tickets_page')):
            response=self.client.get(reverse(route))
            self.assertEqual(len(response.context[key]),0)
            self.assertNotContains(response,'table-proof-')
            self.assertNotContains(response,'Concern 00')


class SerialSQLiteServer(ThreadedWSGIServer):
    """The in-memory test DB shares one connection across request threads."""
    request_lock = Lock()

    def set_app(self, app):
        # Serialize application/database work, not an entire keep-alive socket:
        # browsers download styles/scripts over several concurrent connections.
        def serialized(environ, start_response):
            with self.request_lock:
                return app(environ, start_response)
        super().set_app(serialized)


class SerialSQLiteServerThread(LiveServerThread):
    server_class = SerialSQLiteServer


@skipUnless(os.environ.get('RUN_ACCOUNT_TABLES_BROWSER')=='1','Optional browser verification')
@override_settings(SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,REQUEST_RATE_LIMITING_ENABLED=False)
class AccountTableBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor == 'sqlite':
            cls.server_thread_class = SerialSQLiteServerThread
        super().setUpClass()

    def test_account_forms_and_inline_password_verification_never_reload_the_document(self):
        from playwright.sync_api import expect,sync_playwright
        from .booking_changes import snapshot
        user=account_fixture();user.set_password('ExistingPassword!25');user.save(update_fields=['password'])
        Package.objects.create(name='Package 1-A',price=5000)
        pending=Booking.objects.create(user=user,event_type='Birthday',event_date=timezone.localdate()+timedelta(days=80),
            event_location='A complete venue address in Cavite',status='pending',total_price=6000,package_type='Package 1-A',
            event_time='07:00',event_end_time='10:00',duration_minutes=180,design_theme='Elegant',color_palette='Blue, Gold',
            event_lat='14.414000',event_lng='120.982000')
        completed=Booking.objects.filter(user=user,status='completed').first()
        confirmed=Booking.objects.filter(user=user,status='confirmed').order_by('-pk').first()
        original=snapshot(confirmed)
        change=BookingChangeRequest.objects.create(booking=confirmed,reason='A pending change to withdraw',
            original=original,proposed={**original,'motto_text':'A requested change'},original_total=100,quoted_total=100)
        self.client.force_login(user)
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            def map_asset(route):
                path=artifacts/route.request.url.rsplit('/',1)[-1]
                route.fulfill(path=str(path)) if path.exists() else route.abort()
            context.route('https://unpkg.com/**',map_asset)
            context.route('https://*.tile.openstreetmap.org/**',lambda route:route.abort())
            sweetalert=artifacts/'sweetalert2.all.min.js'
            if sweetalert.exists(): context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11',lambda route:route.fulfill(path=str(sweetalert)))
            page=context.new_page();documents=[];errors=[]
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            page.on('pageerror',lambda error:errors.append(str(error)))
            try:
                page.goto(self.live_server_url+reverse('my_profile'),wait_until='domcontentloaded')
                avatar=page.locator('.account-sidebar-avatar')
                self.assertEqual(avatar.evaluate('(e)=>getComputedStyle(e).fontFamily'),page.locator('.profile-avatar-btn .nav-avatar').evaluate('(e)=>getComputedStyle(e).fontFamily'))
                self.assertEqual(page.locator('.my-profile-header').evaluate('(e)=>getComputedStyle(e).borderBottomWidth'),'0px')
                page.locator('.btn-edit-profile').click()
                page.locator('#profile_first_name').fill('Alex')
                page.get_by_role('button',name='Save Changes',exact=True).click()
                expect(page.locator('.my-profile-title h2')).to_have_text('Alex Rivera')
                expect(page.locator('.account-sidebar-avatar')).to_have_text('A')
                expect(page.locator('.profile-avatar-btn .nav-avatar')).to_have_text('A')
                page.locator('.btn-change-password').click()
                page.locator('#id_old_password').fill('ExistingPassword!25')
                page.locator('#id_new_password1').fill('NewPassword!26')
                page.locator('#id_new_password2').fill('NewPassword!26')
                page.get_by_role('button',name='Send Verification Code',exact=True).click()
                expect(page.locator('#profilePasswordOtpDialog')).to_be_visible()
                expect(page.locator('#profileOtpSubmit')).to_be_enabled()
                code=re.search(r'(?m)^\d{6}$',mail.outbox[-1].body).group()
                page.locator('#profileOtpCode').fill('000000' if code!='000000' else '111111')
                page.locator('#profileOtpSubmit').click()
                expect(page.locator('#profileOtpFeedback')).to_contain_text('invalid')
                page.get_by_role('button',name='Close password verification',exact=True).click()
                page.locator('.btn-change-password').click()
                page.locator('[data-password-resume]').click()
                expect(page.locator('#profileOtpSubmit')).to_be_enabled()
                page.locator('#profileOtpCode').fill(code)
                page.locator('#profileOtpSubmit').click()
                expect(page.locator('#profilePasswordOtpDialog')).not_to_be_visible()
                page.wait_for_function('!window.AccountNavigation.navigating')
                self.assertEqual(page.url,self.live_server_url+reverse('my_profile'))
                self.assertNotEqual(page.evaluate('document.body.style.overflow'),'hidden')
                page.locator('[data-account-key="customer_profile"]').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','customer_profile')
                page.wait_for_function('!window.AccountNavigation.navigating')
                page.locator(f'[onclick="openEditModal(\'{pending.pk}\')"]').first.click()
                page.locator('#btnNextEditStep').click()
                page.locator('#btnNextEditPreview').click()
                page.locator('#btnNextEditToSummary').click()
                page.locator('#edit_special_requests').fill('Saved without a page reload')
                page.locator('#btnNextEditDesignToReview').click()
                with page.expect_response(lambda response:'/edit/' in response.url and response.request.method=='POST') as updated:
                    page.locator('#editBookingForm [type="submit"]').click()
                self.assertEqual(updated.value.status,200)
                expect(page.locator('#editBookingModal')).not_to_be_visible()
                page.wait_for_function('!window.AccountNavigation.navigating')
                page.locator(f'[onclick="openDeleteModal(\'{pending.pk}\')"]').click()
                page.get_by_role('button',name='Yes, Delete',exact=True).click()
                expect(page.locator('#deleteBookingModal')).not_to_be_visible()
                page.wait_for_function('!window.AccountNavigation.navigating')
                expect(page.locator(f'[onclick="openDeleteModal(\'{pending.pk}\')"]')).to_have_count(0)
                page.evaluate('(id)=>openReviewModal(id)',completed.pk)
                page.locator('#reviewModal label[for="star5"]').click()
                page.locator('#reviewModal [name="comment"]').fill('A review submitted without a full reload.')
                page.locator('#reviewForm [type="submit"]').click()
                expect(page.locator('#reviewModal')).not_to_be_visible()
                page.wait_for_function('!window.AccountNavigation.navigating')
                page.locator(f'[onclick="openBookingModal(\'{confirmed.pk}\')"]').click()
                expect(page.locator('#bookingModal .customer-booking-content')).to_contain_text('Withdraw request')
                page.get_by_role('button',name='Withdraw request / keep original booking',exact=True).click()
                expect(page.locator('#bookingModal .customer-booking-content')).to_contain_text('Request withdrawn')
                page.locator('#bookingModal a').filter(has_text='View payment history').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page','my_payments')
                page.wait_for_function('!window.AccountNavigation.navigating')
                self.assertEqual(len(documents),1,documents)
                self.assertEqual(errors,[])
            except Exception:
                page.screenshot(path=str(artifacts/'account-mutations-failure.png'),animations='disabled')
                print('Mutation browser:',page.url,page.locator('[data-account-form-message]').all_text_contents())
                raise
            finally:
                context.close();browser.close()

    def test_search_clear_dropdown_paging_payment_details_concerns_themes_and_mobile(self):
        from playwright.sync_api import expect,sync_playwright
        user=account_fixture(); self.client.force_login(user)
        latest=Payment.objects.order_by('-pk').first()
        long_location='PowerTechnic Lighting Inc., Muelle de la Industria, San Nicolas, Manila, Capital District, Metro Manila, 1010, Philippines'
        latest.booking.event_location=long_location
        latest.booking.package_type='Package 3 + Entrance C + Stand B'
        latest.booking.save(update_fields=['event_location','package_type'])
        change=BookingChangeRequest.objects.create(booking=latest.booking,status='applied',
            reason='An already applied change',original_total=100,quoted_total=100)
        latest.change_request=change;latest.save(update_fields=['change_request'])
        artifacts=Path(settings.BASE_DIR)/'.booking-followup-check'; artifacts.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            context.route('https://fonts.googleapis.com/**',lambda route:route.abort())
            context.route('https://unpkg.com/**',lambda route:route.abort())
            sweetalert=artifacts/'sweetalert2.all.min.js'
            if sweetalert.exists(): context.route('https://cdn.jsdelivr.net/npm/sweetalert2@11',lambda route:route.fulfill(path=str(sweetalert)))
            page=context.new_page(); errors=[]; documents=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('console',lambda message:print('Browser:',message.text) if message.type=='warning' and 'Account list' in message.text else None)
            page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
            def idle():
                expect(page.locator('[data-list-results][aria-busy="true"]')).to_have_count(0)
                page.wait_for_function('!window.AccountNavigation.navigating')
            def visit(route):
                page.locator(f'[data-account-key="{route}"]').click()
                expect(page.locator('#accountContent')).to_have_attribute('data-account-page',route)
                idle()
            def check_kpi_colors():
                colors=page.locator('.account-kpi').evaluate_all('''cards=>cards.map(card=>
                    ['.account-kpi-label','.account-kpi-value','.account-kpi-icon'].map(selector=>
                        getComputedStyle(card.querySelector(selector)).color))''')
                self.assertEqual(len(colors),4)
                self.assertTrue(all(label==value==icon for label,value,icon in colors),colors)
                self.assertEqual(len({row[0] for row in colors}),4,colors)
            try:
                page.goto(self.live_server_url+reverse('customer_profile'),wait_until='domcontentloaded')
                page.evaluate('document.documentElement.dataset.theme="light"')
                check_kpi_colors()
                page.evaluate('''() => { window.tableHistory=[]; const push=history.pushState.bind(history); history.pushState=(state,title,url)=>{window.tableHistory.push(String(url)); return push(state,title,url);}; }''')
                page.screenshot(path=str(artifacts/'account-tables-initial.png'),animations='disabled')
                expect(page.locator('[data-booking-row]')).to_have_count(8)
                self.assertEqual(page.locator('.account-kpi-icon svg').count(),4)
                self.assertEqual(page.locator('.account-kpi-icon i').count(),0)
                self.assertEqual(page.locator('.account-row-actions').first.evaluate('(el)=>getComputedStyle(el).justifyContent'),'flex-start')
                page.locator('#searchFilterInput').fill('no-such-event')
                expect(page.locator('.account-empty-state')).to_contain_text('No matching bookings')
                page.get_by_role('button',name='Clear booking search',exact=True).click()
                expect(page.locator('[data-booking-row]')).to_have_count(8)
                expect(page.get_by_role('button',name='Clear booking search',exact=True)).to_be_hidden()
                page.get_by_role('button',name='Booking status: All Status',exact=True).click()
                page.get_by_role('option',name='Completed',exact=True).click()
                expect(page.locator('#bookings-results')).to_contain_text('of 18')
                page.get_by_role('link',name='Next page',exact=True).click()
                expect(page.locator('.account-table-summary')).to_contain_text('9–16')
                page.get_by_role('button',name='Rows per page: 8',exact=True).click()
                page.keyboard.press('Home')
                expect(page.get_by_role('option',name='4',exact=True)).to_be_focused()
                page.keyboard.press('Enter')
                expect(page.locator('[data-booking-row]')).to_have_count(4)
                page.go_back(wait_until='commit')
                expect(page.locator('[data-booking-row]')).to_have_count(8)
                page.go_forward(wait_until='commit')
                expect(page.locator('[data-booking-row]')).to_have_count(4)
                visit('my_payments')
                expect(page.locator('.cp-tab-panel.is-active [data-payment-row]')).to_have_count(8)
                page.locator('[data-tab-target="payment_history"]').click()
                expect(page.locator('[data-tab-panel="payment_history"]')).to_have_class('cp-tab-panel is-active')
                expect(page.locator('.cp-tab-panel.is-active [data-payment-row]')).to_have_count(8)
                self.assertEqual(page.locator('.account-kpi-icon i').count(),0)
                badges=page.locator('.cp-tab-panel.is-active .mp-status').evaluate_all('(elements)=>elements.map(el=>{const r=el.getBoundingClientRect();return [r.x,r.width,r.height]})')
                self.assertTrue(all(all(abs(a-b)<1 for a,b in zip(badge,badges[0])) for badge in badges),badges)
                change_status=page.locator('.cp-tab-panel.is-active .account-payment-statuses').first
                expect(change_status.locator('.mp-status')).to_have_text('Verified')
                expect(change_status.locator('.mp-chip')).to_have_text(f'Booking change #{change.pk}')
                expect(page.locator('.cp-tab-panel.is-active .account-payment-statuses .mp-chip')).to_have_count(1)
                page.locator('.cp-tab-panel.is-active [data-source="history"]').first.click()
                expect(page.locator('#bookingModal')).to_have_class('cp-modal-overlay active')
                expect(page.locator('#modal-pay-amount')).to_contain_text('30.00')
                expect(page.locator('#modal-location')).to_have_text(long_location)
                expect(page.locator('#modal-package')).to_have_text('Package 3 + Entrance C + Stand B')
                close_details=page.get_by_role('button',name='Close payment details',exact=True)
                expect(close_details).to_be_focused()
                page.get_by_role('button',name='Done',exact=True).focus()
                page.keyboard.press('Tab')
                expect(close_details).to_be_focused()
                page.keyboard.press('Shift+Tab')
                expect(page.get_by_role('button',name='Done',exact=True)).to_be_focused()
                for theme in ('light','dark'):
                    for width,height in ((1440,1000),(390,844),(320,568)):
                        page.set_viewport_size({'width':width,'height':height})
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        details=page.locator('#bookingModal .cp-modal')
                        bounds=details.bounding_box()
                        self.assertGreaterEqual(bounds['x'],0)
                        self.assertGreaterEqual(bounds['y'],0)
                        self.assertLessEqual(bounds['x']+bounds['width'],width)
                        self.assertLessEqual(bounds['y']+bounds['height'],height)
                        body=page.locator('#bookingModal .cp-modal-body')
                        self.assertTrue(body.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'))
                        body.evaluate('(el)=>el.scrollTop=el.scrollHeight')
                        expect(close_details).to_be_in_viewport()
                        body.evaluate('(el)=>el.scrollTop=0')
                        details.screenshot(path=str(artifacts/f'payment-details-{theme}-{width}.png'),animations='disabled')
                page.set_viewport_size({'width':1440,'height':1000})
                page.keyboard.press('Escape')
                expect(page.locator('#bookingModal')).to_have_attribute('aria-hidden','true')
                expect(page.locator('.cp-tab-panel.is-active [data-source="history"]').first).to_be_focused()
                page.locator('.cp-tab-panel.is-active').get_by_role('link',name='Next page',exact=True).click()
                expect(page.locator('.cp-tab-panel.is-active .account-table-summary')).to_contain_text('9–16')
                search=page.get_by_role('searchbox',name='Search payment history',exact=True)
                search.fill('balance-proof')
                expect(page.locator('.cp-tab-panel.is-active .account-table-summary')).to_contain_text('of 9')
                expect(search).to_be_focused()
                search.press('End')
                search.press_sequentially('-08')
                expect(page.locator('.cp-tab-panel.is-active [data-payment-row]')).to_have_count(1)
                expect(search).to_be_focused()
                page.get_by_role('button',name='Clear payment search',exact=True).click()
                expect(page.locator('.cp-tab-panel.is-active [data-payment-row]')).to_have_count(8)
                page.route('**/my-payments/?*',lambda route:route.fulfill(status=503,body='Unavailable'))
                page.locator('.cp-tab-panel.is-active').get_by_role('link',name='Next page',exact=True).click()
                expect(page.locator('.account-list-notice')).to_contain_text('current results are still here')
                expect(page.locator('.cp-tab-panel.is-active [data-payment-row]')).to_have_count(8)
                page.unroute('**/my-payments/?*')
                page.locator('.account-list-notice').get_by_role('button',name='Try again',exact=True).click()
                expect(page.locator('.cp-tab-panel.is-active .account-table-summary')).to_contain_text('9–16')
                visit('report_concern')
                page.locator('#subject').fill('Keep my unfinished report')
                page.get_by_role('link',name='Next page',exact=True).click()
                expect(page.locator('.account-table-summary')).to_contain_text('9–16')
                expect(page.locator('#subject')).to_have_value('Keep my unfinished report')
                page.locator('[data-view-id]').first.click()
                expect(page.locator('#concernDetailModal')).to_be_visible()
                expect(page.locator('#modalSubject')).to_contain_text('Concern')
                page.get_by_role('button',name='Close concern details',exact=True).click()
                # All five headings share the concern heading metrics.
                headings=[]
                for route in ('report_concern','my_profile','customer_profile','my_payments','my_reviews'):
                    visit(route)
                    headings.append(page.locator('.account-page-title').evaluate('(el)=>{const s=getComputedStyle(el),p=getComputedStyle(document.querySelector(".account-page-subtitle"));return [s.fontSize,s.fontWeight,s.letterSpacing,p.fontSize,p.fontWeight,p.marginTop,p.lineHeight]}'))
                self.assertTrue(all(value==headings[0] for value in headings),headings)
                visit('customer_profile')
                logout=page.locator('.account-sidebar-logout'); normal=logout.evaluate('(el)=>getComputedStyle(el).color')
                logout.hover(); self.assertEqual(logout.evaluate('(el)=>getComputedStyle(el).color'),normal)
                for route in ('customer_profile','my_payments','report_concern'):
                    visit(route)
                    for theme in ('light','dark'):
                        for width,height in ((1440,1000),(390,844),(320,568)):
                            page.set_viewport_size({'width':width,'height':height})
                            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                            if route in ('customer_profile','my_payments'):
                                check_kpi_colors()
                            page.wait_for_function('document.documentElement.scrollWidth<=innerWidth+1')
                            page.evaluate('scrollTo(0,0)')
                            page.screenshot(path=str(artifacts/f'account-table-{route}-{theme}-{width}.png'),animations='disabled')
                            if width==1440:
                                page.locator('[data-list-footer]:visible').first.screenshot(path=str(artifacts/f'account-footer-{route}-{theme}.png'),animations='disabled')
                    page.set_viewport_size({'width':1440,'height':1000})
                page.emulate_media(reduced_motion='no-preference')
                page.evaluate('''() => {
                    window.accountEntryRuns=0;
                    const animate=Element.prototype.animate;
                    Element.prototype.animate=function(frames,options) {
                        if (options?.id==='account-entry') window.accountEntryRuns++;
                        return animate.call(this,frames,options);
                    };
                }''')
                visit('my_profile')
                page.wait_for_function('window.accountEntryRuns>0')
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_function('!document.getElementById("accountContent").getAnimations({subtree:true}).some(animation=>animation.id==="account-entry")')
                self.assertEqual(errors,[])
                self.assertEqual(len(documents),1)
            except Exception:
                print('Table browser failure:',page.url,page.locator('.account-list-notice').all_text_contents(),page.evaluate('window.tableHistory'))
                try:
                    page.screenshot(path=str(artifacts/'account-tables-failure.png'),animations='disabled',timeout=3000)
                except Exception:
                    pass
                raise
            finally:
                context.close(); browser.close()
