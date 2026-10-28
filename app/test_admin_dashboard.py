"""Dashboard reporting parity, operational scope, dates and authorization."""
from datetime import date, datetime, timedelta, time, timezone as utc
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .analytics_reporting import build_report, resolve_filters
from .dashboard_reporting import build_dashboard, current_operations, dashboard_filters, dashboard_greeting
from .models import Booking, BookingChangeRequest, ConcernTicket, Payment, User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminDashboardTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username='dashboard-admin',role='admin',email_verified=True)
        self.customer=User.objects.create_user(username='dashboard-customer',first_name='Jamie',last_name='Rivera',role='customer',email_verified=True)
        self.client.force_login(self.admin);self.url=reverse('dashboard')
        self.ajax={'HTTP_X_REQUESTED_WITH':'XMLHttpRequest'}
        self.enterContext(patch('django.utils.timezone.now',return_value=datetime(2026,10,26,4,tzinfo=utc.utc)))

    def booking(self,day='2026-10-26',status='pending',value='1000',**kwargs):
        return Booking.objects.create(user=self.customer,event_date=day,event_time=kwargs.pop('event_time',time(9)),
            event_type=kwargs.pop('event_type','Birthday'),package_type='Package 1-A',event_location='Venue',
            status=status,total_price=value,**kwargs)

    def payment(self,booking,amount='100',**kwargs):
        return Payment.objects.create(booking=booking,amount=amount,payment_method=kwargs.pop('payment_method','gcash'),
            payment_status=kwargs.pop('payment_status','verified'),transaction_ref=f'DASH-{Payment.objects.count()}',**kwargs)

    def test_default_week_is_seven_days_and_fields_are_iso_dates(self):
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,200);filters=response.context['filters']
        self.assertEqual(filters.start,date(2026,10,20));self.assertEqual(filters.end,date(2026,10,26))
        self.assertContains(response,'name="start_date" value="2026-10-20"')
        self.assertContains(response,'name="end_date" value="2026-10-26"')
        self.assertContains(response,"You're all caught up");self.assertContains(response,'No events scheduled this week')

    def test_greeting_uses_philippine_time_at_day_period_boundaries(self):
        for hour,expected in ((4,'Good evening'),(5,'Good morning'),(11,'Good morning'),
                (12,'Good afternoon'),(17,'Good afternoon'),(18,'Good evening'),(23,'Good evening')):
            stamp=datetime(2026,10,26,hour,tzinfo=utc(timedelta(hours=8)))
            with self.subTest(hour=hour):
                self.assertEqual(dashboard_greeting(stamp.astimezone(utc.utc)),expected)
        response=self.client.get(self.url)
        self.assertContains(response,'Good afternoon')
        self.assertContains(response,'Administrator.')
        html=response.content.decode()
        self.assertLess(html.index('id="dashboardResults"'),html.index('id="dashboardOperations"'))

    def test_today_uses_manila_midnight_in_both_reporting_and_schedule(self):
        self.booking(day='2026-10-27',status='confirmed')
        with patch('django.utils.timezone.now',return_value=datetime(2026,10,26,17,tzinfo=utc.utc)):
            data=build_dashboard(dashboard_filters({'filter_preset':'today'}))
        self.assertEqual(data['filters'].start,date(2026,10,27));self.assertEqual(data['total_bookings'],1)
        self.assertEqual(data['operations_now'].date(),date(2026,10,27));self.assertEqual(data['today_event_count'],1)

    def test_month_to_date_and_previous_month_use_same_elapsed_days(self):
        filters=dashboard_filters({'filter_preset':'month'})
        self.assertEqual((filters.start,filters.end),(date(2026,10,1),date(2026,10,26)))
        self.assertEqual((filters.previous_start,filters.previous_end),(date(2026,9,1),date(2026,9,26)))
        self.booking(day='2026-10-31');self.assertEqual(build_dashboard(filters)['total_bookings'],0)

    def test_all_time_includes_future_bookings_and_disables_fake_comparison(self):
        self.booking(day='2027-03-01');self.booking(day='2020-01-01')
        data=build_dashboard(dashboard_filters({'filter_preset':'all'}))
        self.assertEqual(data['total_bookings'],2);self.assertIsNone(data['filters'].previous_start)
        self.assertIsNone(data['comparison']['count']['percent'])

    def test_same_cohort_money_statuses_graphs_and_analytics_without_payment_duplicates(self):
        done=self.booking(status='completed',value='1200.25')
        self.payment(done,'300.15');self.payment(done,'200.10')
        self.payment(done,'800',payment_status='pending');self.payment(done,'999',payment_status='rejected')
        self.payment(done,'900',applied_to_booking=False)
        self.booking(status='confirmed');self.booking(status='cancelled');self.booking(status='cancel_requested')
        self.booking(day='2026-11-01',status='completed',value='9000')
        filters=dashboard_filters({'filter_preset':'today'})
        dashboard=build_dashboard(filters);analytics=build_report(filters)
        for key in ('total_bookings','completed_value','verified_collections','completion_rate','cancellation_rate','customer_count','statuses','kpis'):
            self.assertEqual(dashboard[key],analytics[key],key)
        self.assertEqual(dashboard['total_bookings'],4);self.assertEqual(dashboard['completed_value'],Decimal('1200.25'))
        self.assertEqual(dashboard['verified_collections'],Decimal('500.25'))
        self.assertEqual(sum(row['count'] for row in dashboard['statuses']),4)
        self.assertEqual(sum(dashboard['charts']['trend']['series']['bookings']['current']),4)
        self.assertEqual(sum(dashboard['charts']['trend']['series']['collections']['current']),500.25)
        self.assertEqual(dashboard['charts']['insights'],{})

    def test_submission_date_and_event_type_filter_every_period_metric(self):
        future=self.booking(day='2026-12-01',status='confirmed',event_type='Wedding')
        self.booking(day='2026-10-26',status='completed',event_type='Birthday')
        params={'filter_preset':'today','date_basis':'created','event_type':'Wedding'}
        data=build_dashboard(dashboard_filters(params))
        self.assertEqual(data['total_bookings'],1);self.assertEqual(data['completed_value'],0)
        self.assertEqual(data['charts']['trend']['series']['bookings']['current'],[1])
        data=build_dashboard(dashboard_filters({**params,'date_basis':'event'}));self.assertEqual(data['total_bookings'],0)

    def test_operations_are_current_and_not_hidden_by_reporting_filters(self):
        pending=self.booking(day='2027-01-01')
        self.payment(pending,payment_status='pending')
        self.payment(pending,payment_status='pending',payment_method='paymongo_gcash',notes='Customer left the PayMongo checkout')
        self.booking(status='cancel_requested');self.booking(status='confirmed')
        self.booking(day='2026-11-01',status='confirmed');self.booking(day='2026-11-02',status='confirmed')
        self.booking(day='2026-10-25',status='confirmed')
        self.booking(status='pending_payment')
        ConcernTicket.objects.create(user=self.customer,category='bug',subject='A bug',message='Help please')
        BookingChangeRequest.objects.create(booking=pending,status='pending_review',reason='Change venue',original_total=1000,quoted_total=1000)
        data=build_dashboard(dashboard_filters({'start_date':'2020-01-01','end_date':'2020-01-02'}))
        self.assertEqual(data['total_bookings'],0);self.assertEqual(data['queue_counts'],{'approvals':1,'cancellations':1,'payments':1,'changes':1,'concerns':1})
        self.assertEqual(data['upcoming_count'],3);self.assertEqual(data['today_event_count'],2)
        for queue in data['queues']:
            self.assertTrue(queue['url'].startswith('/staff/'));self.assertNotIn('needs_action',queue['url'])
        response=self.client.get(self.url)
        self.assertEqual(response.context['pending_bookings_count'],data['queue_counts']['approvals'])
        self.assertEqual(response.context['pending_payments_count'],data['queue_counts']['payments'])
        self.assertEqual(response.context['new_concerns_count'],data['queue_counts']['concerns'])

    def test_upcoming_stable_order_unknown_time_and_five_record_bound(self):
        unknown=self.booking(status='confirmed',event_time=None)
        early=self.booking(status='confirmed',event_time=time(7))
        for day in range(27,32):self.booking(day=f'2026-10-{day}',status='confirmed')
        data=current_operations()
        self.assertEqual([row.pk for row in data['upcoming_events']][:2],[early.pk,unknown.pk])
        self.assertEqual(len(data['upcoming_events']),5);self.assertEqual(data['upcoming_count'],7)
        response=self.client.get(self.url);self.assertContains(response,'Time not set')

    def test_invalid_filters_rejected_with_no_data_mutation(self):
        booking=self.booking();Booking.objects.filter(pk=booking.pk).update(edit_requested=True)
        invalid=[{'start_date':'bad','end_date':'2026-10-26'},{'start_date':'2026-10-26'},
            {'start_date':'2026-11-01','end_date':'2026-10-01'},{'filter_preset':'invalid'},
            {'date_basis':'bad'},{'event_type':'not a real event'}]
        for params in invalid:
            with self.subTest(params=params):
                response=self.client.get(self.url,params,**self.ajax)
                self.assertEqual(response.status_code,400);self.assertTrue(response.json()['error'])
        with CaptureQueriesContext(connection) as queries:self.client.get(self.url,{'filter_preset':'today'},**self.ajax)
        self.assertFalse(any(query['sql'].lstrip().upper().startswith(('UPDATE ','DELETE ','INSERT ')) for query in queries))
        booking.refresh_from_db();self.assertTrue(booking.edit_requested)

    def test_async_response_fallback_and_no_previous_zero_percentage_claim(self):
        self.booking()
        response=self.client.get(self.url,{'filter_preset':'today'},**self.ajax)
        self.assertEqual(response.status_code,200);data=response.json()
        self.assertIn('no % baseline',data['html']);self.assertIn('Current operations',data['operations_html'])
        self.assertIn('date_basis=event',data['analytics_url']);self.assertIn('start_date=2026-10-26',data['analytics_url'])
        self.assertNotIn('filter_preset=',data['analytics_url']);self.assertIn('comparison=period',data['analytics_url'])
        # Opening Analytics later must keep the dates actually shown here.
        with patch('django.utils.timezone.now',return_value=datetime(2026,10,27,4,tzinfo=utc.utc)):
            analytics=self.client.get(data['analytics_url'])
        self.assertEqual(analytics.context['total_bookings'],1)
        self.assertEqual(analytics.context['filters'].start,date(2026,10,26))
        self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertNotIn('<html',data['html'])
        fallback=self.client.get(self.url,{'start_date':'bad','end_date':'bad'})
        self.assertContains(fallback,'Enter both a valid start date and end date.')

    def test_admin_only_and_read_only_endpoint(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url,**self.ajax).status_code,403)
        self.client.force_login(self.admin);self.assertEqual(self.client.post(self.url,**self.ajax).status_code,405)
        self.client.logout();self.assertEqual(self.client.get(self.url).status_code,302)
