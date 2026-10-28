"""Global search is private, bounded, read-only and linked to exact admin records."""
from datetime import date, time

from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone

from .admin_navigation import admin_breadcrumbs, search_records
from .models import Booking, Payment, User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminNavigationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username='navigation-admin',email='admin@example.com',role='admin',email_verified=True)
        self.customer=User.objects.create_user(username='jamier',first_name='Jamie',last_name='Rivera',email='jamie@example.com',
            phone_number='09171234567',role='customer',email_verified=True)
        self.booking=Booking.objects.create(user=self.customer,event_date=date(2026,10,30),event_time=time(10),event_type='Birthday',
            event_location='Test venue',package_type='Package 1-A',total_price=5000,status='confirmed')
        self.payment=Payment.objects.create(booking=self.booking,amount=2500,payment_method='gcash',payment_status='verified',transaction_ref='SEARCH-PAY-ABC123')
        self.url=reverse('admin_global_search');self.client.force_login(self.admin)

    def crumbs(self,name,kwargs=None,query=None):
        request=RequestFactory().get(reverse(name,kwargs=kwargs),data=query or {})
        request.resolver_match=resolve(request.path)
        return admin_breadcrumbs(request)

    def test_search_requires_authenticated_admin_and_only_get(self):
        self.client.force_login(self.customer)
        response=self.client.get(self.url,{'q':'Jamie'})
        self.assertEqual(response.status_code,403);self.assertNotIn('Jamie',response.content.decode())
        self.client.logout();self.assertEqual(self.client.get(self.url,{'q':'Jamie'}).status_code,302)
        self.client.force_login(self.admin);self.assertEqual(self.client.post(self.url,{'q':'Jamie'}).status_code,405)

    def test_name_email_and_exact_record_links(self):
        for query in ('Jamie Rivera','jamie@example.com'):
            with self.subTest(query=query):
                response=self.client.get(self.url,{'q':query});self.assertEqual(response.status_code,200)
                groups={group['key']:group['items'] for group in response.json()['groups']}
                self.assertEqual(groups['bookings'][0]['url'],reverse('admin_booking_detail',args=[self.booking.pk]))
                self.assertEqual(groups['customers'][0]['url'],reverse('admin_user_detail',args=[self.customer.pk]))
                self.assertEqual(groups['payments'][0]['url'],reverse('admin_payment_detail',args=[self.payment.pk]))
                self.assertIn('private',response['Cache-Control']);self.assertIn('no-store',response['Cache-Control'])
        customer_results=search_records(self.admin.email)
        self.assertFalse(any(group['key']=='customers' for group in customer_results['groups']))

    def test_ids_references_and_phone_search(self):
        result=search_records(f'booking:{self.booking.pk}')
        self.assertEqual([g['key'] for g in result['groups']],['bookings','payments'])
        result=search_records(f'payment #{self.payment.pk}')
        self.assertEqual([g['key'] for g in result['groups']],['payments'])
        self.assertEqual(result['groups'][0]['items'][0]['url'],reverse('admin_payment_detail',args=[self.payment.pk]))
        result=search_records('SEARCH-PAY-ABC123')
        self.assertEqual(result['groups'][0]['key'],'payments')
        result=search_records('09171234567')
        self.assertEqual(result['groups'][0]['items'][0]['title'],'Jamie Rivera')
        result=search_records(f'customer:{self.customer.pk}')
        self.assertEqual({g['key'] for g in result['groups']},{'customers','bookings','payments'})

    def test_results_bounded_no_extra_fields_and_stable(self):
        for index in range(7):
            Booking.objects.create(user=self.customer,event_date=date(2026,11,1),event_type='Birthday',event_location='Venue',total_price=100,status='pending')
            User.objects.create_user(username=f'rivera{index}',first_name='Jamie',last_name='Rivera',role='customer')
            Payment.objects.create(booking=self.booking,amount=100,payment_method='gcash',payment_status='pending',transaction_ref=f'SEARCH-RIVERA-{index}')
        first=search_records('Jamie');second=search_records('Jamie')
        self.assertEqual(first,second);self.assertTrue(first['has_more'])
        self.assertTrue(all(len(group['items'])<=4 for group in first['groups']))
        for group in first['groups']:
            for item in group['items']:
                self.assertEqual(set(item),{'title','description','url'})
                self.assertTrue(item['url'].startswith('/staff/'))

    def test_removed_customer_and_abandoned_checkout_not_suggested(self):
        self.customer.deleted_at=timezone.now();self.customer.save(update_fields=['deleted_at'])
        Payment.objects.create(booking=self.booking,amount=100,payment_method='paymongo_gcash',payment_status='pending',
            transaction_ref='SEARCH-ABANDONED',notes='Customer left the PayMongo checkout')
        result=search_records('Jamie')
        self.assertFalse(any(group['key']=='customers' for group in result['groups']))
        result=search_records('SEARCH-ABANDONED');self.assertEqual(result['groups'],[])

    def test_empty_short_invalid_and_escaped_queries_do_not_crash(self):
        for query in ('','  ','J','<script>alert(1)</script>','%_','9'*30):
            self.assertEqual(self.client.get(self.url,{'q':query}).status_code,200)
        self.assertEqual(self.client.get(self.url,{'q':'x'*121}).status_code,400)
        self.assertEqual(self.client.get(self.url,{'q':'abc\x00def'}).status_code,400)
        with CaptureQueriesContext(connection) as queries:search_records('')
        self.assertEqual(len(queries),0)
        with CaptureQueriesContext(connection) as queries:search_records('Jamie Rivera')
        self.assertLessEqual(len(queries),3)
        self.assertFalse(any(query['sql'].lstrip().upper().startswith(('UPDATE ','INSERT ','DELETE ')) for query in queries))

    def test_breadcrumbs_page_and_nested_actions_are_exact(self):
        self.assertEqual(self.crumbs('dashboard'),[{'label':'Dashboard','url':''}])
        crumbs=self.crumbs('admin_booking_detail',{'id':self.booking.pk})
        self.assertEqual([row['label'] for row in crumbs],['Dashboard','Bookings',f'Booking #{self.booking.pk}'])
        self.assertEqual(crumbs[1]['url'],reverse('admin_booking_list'));self.assertEqual(crumbs[-1]['url'],'')
        self.assertEqual(self.crumbs('admin_booking_list',query={'tab':'requests'})[-1]['label'],'Change requests')
        crumbs=self.crumbs('admin_booking_change_detail',{'change_id':17})
        self.assertEqual(crumbs[-2]['url'],reverse('admin_booking_list')+'?tab=requests')
        self.assertEqual(crumbs[-1]['label'],'Request #17')
        self.assertEqual(self.crumbs('admin_user_edit',{'id':self.customer.pk})[-1]['label'],f'Edit user #{self.customer.pk}')
        self.assertEqual(self.crumbs('admin_addon_create')[-1]['label'],'Add entrance arch')
        self.assertEqual(self.crumbs('admin_analytics')[-1]['label'],'Reports & Analytics')
        self.assertEqual(self.crumbs('admin_gcash_config')[-1]['label'],'GCash settings')

    def test_topbar_shared_markup_links_and_customer_page_exclusion(self):
        response=self.client.get(reverse('admin_audit_log'))
        self.assertContains(response,'aria-label="Breadcrumb"')
        self.assertContains(response,'aria-label="Search admin records"')
        self.assertContains(response,'target="_blank" rel="noopener noreferrer"')
        self.assertContains(response,'aria-label="View website (opens in a new tab)"')
        self.assertContains(response,reverse('admin_global_search'))
        self.client.force_login(self.customer)
        response=self.client.get(reverse('home'))
        self.assertNotContains(response,'id="adminGlobalSearch"')

    def test_public_navigation_stays_available_to_admins(self):
        for name in ('home','about','services','package','gallery'):
            with self.subTest(page=name):
                response=self.client.get(reverse(name))
                self.assertEqual(response.status_code,200)
                navbar=response.content.decode().split('<nav class="navbar">',1)[1].split('</nav>',1)[0]
                self.assertIn('class="nav-logo"',navbar)
                self.assertIn('class="mobile-menu"',navbar)
                self.assertIn('class="nav-links"',navbar)
                for destination in ('home','about','services','package','gallery','dashboard'):
                    self.assertIn(f'href="{reverse(destination)}"',navbar)
                self.assertNotIn(f'href="{reverse("login")}"',navbar)
                self.assertNotIn('id="notif-bell"',navbar)
                self.assertTrue(response.wsgi_request.user.is_authenticated)
                self.assertEqual(response.wsgi_request.user.role,'admin')

    def test_customer_and_guest_public_navigation_keep_their_own_actions(self):
        self.client.force_login(self.customer)
        response=self.client.get(reverse('home'))
        navbar=response.content.decode().split('<nav class="navbar">',1)[1].split('</nav>',1)[0]
        self.assertIn('class="nav-logo"',navbar)
        self.assertIn('id="clientAccountMenu"',navbar)
        self.assertIn('id="notif-bell"',navbar)
        self.assertNotIn(f'href="{reverse("dashboard")}"',navbar)
        self.client.logout()
        response=self.client.get(reverse('home'))
        navbar=response.content.decode().split('<nav class="navbar">',1)[1].split('</nav>',1)[0]
        self.assertIn('class="nav-logo"',navbar)
        self.assertIn(f'href="{reverse("login")}"',navbar)
        self.assertNotIn('id="clientAccountMenu"',navbar)
        self.assertNotIn(f'href="{reverse("dashboard")}"',navbar)
