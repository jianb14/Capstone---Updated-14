"""Business rules for payment, demand and customer analytics."""
from datetime import datetime, date, time, timezone as utc
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from .analytics_reporting import build_report, resolve_filters
from .models import AdditionalOnly, AddOn, Booking, Package, Payment, Review, User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AnalyticsInsightsTests(TestCase):
    def setUp(self):
        self.customer=User.objects.create_user(username='insights-customer',role='customer',email_verified=True)
        self.other=User.objects.create_user(username='insights-other',role='customer',email_verified=True)
        self.admin=User.objects.create_user(username='insights-admin',role='admin',email_verified=True)
        self.client.force_login(self.admin)
        self.enterContext(patch('app.analytics_reporting.timezone.now',return_value=datetime(2026,10,26,4,tzinfo=utc.utc)))

    def booking(self,status='confirmed',day='2026-10-26',**kwargs):
        return Booking.objects.create(user=kwargs.pop('user',self.customer),status=status,event_date=day,
            event_time=kwargs.pop('event_time',time(9)),event_type=kwargs.pop('event_type','Birthday'),
            total_price=kwargs.pop('total_price','1000.00'),package_type=kwargs.pop('package_type','Package 1-A + Entrance A + Stand A'),
            event_location='Test venue',**kwargs)

    def payment(self,booking,amount,**kwargs):
        return Payment.objects.create(booking=booking,amount=amount,transaction_ref=f'INSIGHT-{Payment.objects.count()}',
            payment_status=kwargs.pop('payment_status','verified'),payment_method=kwargs.pop('payment_method','gcash'),**kwargs)

    def report(self,**params):
        return build_report(resolve_filters({'filter_preset':'today',**params}))

    def test_balances_exclude_quotations_cancelled_expired_and_never_cross_offset(self):
        partial=self.booking('confirmed');self.payment(partial,'250')
        over=self.booking('completed');self.payment(over,'1800')
        done=self.booking('completed');self.payment(done,'100')
        self.booking('pending_payment');self.booking('cancel_requested')
        for status in ('pending','expired','cancelled'):self.booking(status,total_price=9000)
        facts=self.report()['insights']
        self.assertEqual(facts['remaining_balance'],Decimal('3650.00'))
        self.assertEqual(facts['payable_value'],Decimal('5000.00'))
        self.assertEqual(facts['credited_capped'],Decimal('1350.00'))
        self.assertEqual(facts['completed_unpaid'],1)
        self.assertEqual({row['label']:row['count'] for row in facts['payment_progress']},
            {'Fully paid':1,'Partially paid':2,'Unpaid':2})
        self.assertEqual(facts['remaining_balance']+facts['credited_capped'],facts['payable_value'])

    def test_cached_payment_flag_pending_and_unapplied_payments_do_not_reduce_balance(self):
        booking=self.booking(payment_status='paid')
        self.payment(booking,'900',payment_status='pending')
        self.payment(booking,'700',payment_status='rejected')
        self.payment(booking,'500',applied_to_booking=False)
        facts=self.report()['insights']
        self.assertEqual(facts['remaining_balance'],1000)
        self.assertEqual(facts['payment_progress'][-1]['count'],1)

    def test_collections_use_receipt_date_independent_of_booking_date_and_prefer_receipt(self):
        future=self.booking(day='2026-12-01')
        self.payment(future,'300.25',received_at=datetime(2026,10,25,16,tzinfo=utc.utc))
        today=self.booking()
        self.payment(today,'800',received_at=datetime(2026,10,25,15,59,tzinfo=utc.utc),paid_at=datetime(2026,10,26,1,tzinfo=utc.utc))
        self.payment(today,'400',received_at=datetime(2026,10,26,16,tzinfo=utc.utc))
        report=self.report();receipt=report['insights']['collections']
        self.assertEqual(report['total_bookings'],1)
        self.assertEqual(report['verified_collections'],1200)
        self.assertEqual(receipt['value'],Decimal('300.25'))
        self.assertEqual(receipt['trend']['current'],[300.25])
        self.assertEqual(receipt['trend']['previous'],[800])
        self.assertEqual(sum(row['value'] for row in receipt['methods']),receipt['value'])

    def test_receipt_verification_fallback_and_missing_dates_are_explicit(self):
        booking=self.booking()
        self.payment(booking,'100',paid_at=datetime(2026,10,26,2,tzinfo=utc.utc))
        self.payment(booking,'200')
        self.payment(booking,'300',payment_status='pending',received_at=datetime(2026,10,26,2,tzinfo=utc.utc))
        self.payment(booking,'400',applied_to_booking=False,received_at=datetime(2026,10,26,2,tzinfo=utc.utc))
        facts=self.report()['insights']['collections']
        self.assertEqual((facts['value'],facts['count'],facts['fallback_count'],facts['undated_count']),(100,1,1,1))
        self.assertEqual(facts['trend']['current'],[100])

    def test_receipt_event_filter_and_all_time_include_payments_outside_event_dates(self):
        booking=self.booking(day='2026-12-01')
        self.payment(booking,'150',received_at=datetime(2026,9,1,2,tzinfo=utc.utc))
        wedding=self.booking(event_type='Wedding')
        self.payment(wedding,'999',received_at=datetime(2026,10,26,2,tzinfo=utc.utc))
        report=self.report(filter_preset='all',event_type='Birthday')
        self.assertEqual(report['filters'].start,date(2026,9,1))
        self.assertEqual(report['filters'].end,date(2026,12,1))
        self.assertEqual(report['insights']['collections']['value'],150)
        self.assertEqual(report['total_bookings'],1)

    def test_collections_compare_equal_days_and_month_end_missing_points(self):
        booking=self.booking()
        self.payment(booking,'100',received_at=datetime(2026,10,26,1,tzinfo=utc.utc))
        self.payment(booking,'50',received_at=datetime(2026,9,26,1,tzinfo=utc.utc))
        self.payment(booking,'900',received_at=datetime(2026,9,27,1,tzinfo=utc.utc))
        facts=self.report(filter_preset='month')['insights']['collections']
        self.assertEqual(sum(facts['trend']['previous']),50)
        self.assertEqual(facts['delta']['percent'],100)

    def test_demand_uses_actual_event_dates_committed_states_and_known_hours(self):
        for status in ('confirmed','completed','cancel_requested'):self.booking(status)
        self.booking('confirmed',event_time=None)
        for status in ('pending','pending_payment','expired','cancelled'):self.booking(status)
        facts=self.report()['insights']
        self.assertEqual(facts['committed_count'],4)
        self.assertEqual(sum(row['count'] for row in facts['months']),4)
        self.assertEqual(sum(row['count'] for row in facts['weekdays']),4)
        self.assertEqual(facts['weekdays'][0]['count'],4)
        self.assertEqual(facts['months'][9]['count'],4)
        self.assertEqual(facts['hours'][9]['count'],3)
        self.assertEqual(facts['unknown_time'],1)
        self.assertEqual((facts['expired'],facts['expired_rate']),(1,12.5))

    def test_demand_does_not_mislabel_submission_dates_as_event_dates(self):
        self.booking(day='2026-12-25')
        facts=self.report(date_basis='created')['insights']
        self.assertEqual(facts['months'][11]['count'],1)
        self.assertEqual(facts['weekdays'][4]['count'],1)

    def test_catalog_and_historical_offer_selections_include_solo_arches_and_stands(self):
        Package.objects.create(name='Custom Deluxe',price=1000,features='Test')
        AddOn.objects.create(name='Garden Entry',price=500,features='Test')
        AdditionalOnly.objects.create(name='Personal Welcome',price=100,features='Test')
        self.booking('completed',package_type='custom deluxe + Garden Entry + Personal Welcome + Personal Welcome')
        self.booking(package_type='Entrance A (Solo) + Stand A')
        self.booking(package_type='Package Removed + Entrance Removed + Mystery')
        facts=self.report()['insights']['offers']
        self.assertEqual(sum(row['count'] for row in facts['packages']),2)
        self.assertEqual(sum(row['count'] for row in facts['arches']),3)
        self.assertEqual(sum(row['count'] for row in facts['stands']),2)
        self.assertIn('Entrance A',[row['label'] for row in facts['arches']])
        self.assertEqual(facts['unclassified'],1)
        self.assertEqual(facts['packages'][0]['completed_value']+facts['packages'][1]['completed_value'],1000)

    def test_repeat_customers_require_earlier_completed_events_not_future_or_cancelled_bookings(self):
        self.booking('completed',day='2026-10-20',event_type='Wedding')
        self.booking('completed');self.booking('completed')
        self.booking('completed',user=self.other)
        self.booking('confirmed',day='2026-11-01',user=self.other)
        self.booking('cancelled',day='2026-10-15',user=self.other)
        facts=self.report(event_type='Birthday')['insights']['customers']
        self.assertEqual((facts['completed_customers'],facts['returning'],facts['new']),(2,1,1))
        self.assertEqual(facts['returning_rate'],50)

    def test_future_completed_error_and_unreviewed_events_do_not_invent_bad_ratings(self):
        completed=self.booking('completed');other=self.booking('completed',user=self.other)
        future=self.booking('completed',day='2026-11-01')
        pending=self.booking('pending')
        for booking,rating in [(completed,5),(completed,3),(future,1),(pending,1),(other,8)]:
            Review.objects.create(user=booking.user,booking=booking,rating=rating,comment='Feedback')
        facts=self.report(filter_preset='all')['insights']['customers']
        self.assertEqual(facts['reviews'],2)
        self.assertEqual(facts['average_rating'],4)
        self.assertEqual(facts['reviewed_bookings'],1)
        self.assertEqual(facts['eligible_completed'],2)
        self.assertEqual(facts['review_coverage'],50)
        self.assertEqual(sum(row['count'] for row in facts['ratings']),2)

    def test_empty_denominators_show_unavailable_and_all_tabs_render_empty_states(self):
        facts=self.report()['insights']['customers']
        self.assertIsNone(facts['average_rating']);self.assertIsNone(facts['returning_rate'])
        for tab in ('overview','bookings','payments','customers'):
            response=self.client.get(reverse('admin_analytics'),{'filter_preset':'today','tab':tab},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['filters']['tab'],tab)
            self.assertIn(f'data-report-view="{tab}"',response.json()['html'])
            self.assertIn('ar-chart-empty',response.json()['html'])
            self.assertNotIn('Recent Bookings',response.json()['html'])
        self.assertEqual(self.client.get(reverse('admin_analytics'),{'tab':'unknown'},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,400)

    def test_all_tabs_render_populated_charts_and_use_same_export_filters(self):
        booking=self.booking('completed')
        self.payment(booking,'100',received_at=datetime(2026,10,26,2,tzinfo=utc.utc))
        Review.objects.create(booking=booking,user=self.customer,rating=5,comment='Good')
        for tab in ('bookings','payments','customers'):
            response=self.client.get(reverse('admin_analytics'),{'tab':tab,'filter_preset':'today'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,200)
            self.assertIn('data-chart=',response.json()['html'])
            self.assertIn(f'tab={tab}',response.json()['export_url'])

    def test_query_count_is_bounded_with_completed_customer_history_and_payments(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        filters=resolve_filters({'filter_preset':'today'})
        booking=self.booking('completed');self.payment(booking,100)
        with CaptureQueriesContext(connection) as initial:build_report(filters)
        for _ in range(12):self.booking('completed')
        with CaptureQueriesContext(connection) as expanded:build_report(filters)
        self.assertEqual(len(initial),len(expanded))
        self.assertLessEqual(len(expanded),8)

    def test_ambiguous_catalog_names_are_not_silently_assigned_to_wrong_category(self):
        Package.objects.create(name='Shared name',price=1000,features='Test')
        AddOn.objects.create(name='Shared name',price=500,features='Test')
        self.booking(package_type='Shared name')
        facts=self.report()['insights']['offers']
        self.assertEqual(facts['unclassified'],1)
        self.assertEqual(facts['packages'],[])
        self.assertEqual(facts['arches'],[])

    def test_excel_and_pdf_include_independent_receipts_and_business_insights(self):
        import io
        import openpyxl
        selected=self.booking('confirmed');self.payment(selected,200)
        future=self.booking(day='2026-12-01')
        self.payment(future,300,received_at=datetime(2026,10,26,2,tzinfo=utc.utc))
        response=self.client.get(reverse('admin_analytics_export_excel'),{'filter_preset':'today','tab':'payments'})
        self.assertEqual(response.status_code,200)
        book=openpyxl.load_workbook(io.BytesIO(response.content))
        self.assertEqual(book['Collections Received']['C2'].value,300)
        facts=dict(book['Business Insights'].values)
        self.assertEqual(facts['Remaining balance'],800)
        self.assertEqual(facts['Collections received'],300)
        self.assertIn('Offer Demand',book.sheetnames)
        with patch('app.views.admin.pisa.CreatePDF') as pdf:
            pdf.return_value.err=0
            response=self.client.get(reverse('admin_analytics_export_pdf'),{'filter_preset':'today'})
        self.assertEqual(response.status_code,200)
        html=pdf.call_args.args[0]
        self.assertIn('Payments and Balances',html)
        self.assertIn('PHP 800.00',html)
        self.assertIn('PHP 300.00',html)
        self.assertIn('Customers and Reviews',html)
