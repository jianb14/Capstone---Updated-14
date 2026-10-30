from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse

from .booking_changes import snapshot
from .booking_lifecycle import event_start_at
from .context_processors import _admin_notif_target_url
from .models import Booking, BookingChangeRequest, Payment
from . import test_booking_changes as change_fixtures


class AdminBookingRequestTests(TestCase):
    setUp = change_fixtures.BookingChangeTests.setUp
    data = change_fixtures.BookingChangeTests.data
    submit = change_fixtures.BookingChangeTests.submit
    quote = change_fixtures.BookingChangeTests.quote
    accept = change_fixtures.BookingChangeTests.accept
    proof = change_fixtures.BookingChangeTests.proof

    def make_change(self, status='pending_review', booking=None, **updates):
        if booking is None:
            booking=Booking.objects.get(pk=self.booking.pk)
            booking.pk=None
            booking.event_date+=timedelta(days=Booking.objects.count())
            booking.event_end_date=booking.event_date
            booking.design_due_at=event_start_at(booking)-timedelta(hours=24)
            booking.save()
        original=snapshot(booking);proposed=dict(original)
        proposed['motto_text']=f'New backdrop {BookingChangeRequest.objects.count()}'
        values=dict(booking=booking,status=status,reason=f'Request reason {BookingChangeRequest.objects.count()}',
            original=original,proposed=proposed,original_total=booking.total_price,quoted_total=booking.total_price)
        if status in ('quoted','awaiting_payment'):
            values.update(expires_at=self.now+timedelta(hours=12),hold_start=event_start_at(booking),hold_end=event_start_at(booking)+timedelta(hours=3))
        values.update(updates)
        return BookingChangeRequest.objects.create(**values)

    def queue(self, **query):
        self.client.force_login(self.admin)
        return self.client.get(reverse('admin_booking_list'),{'tab':'requests',**query})

    def test_bookings_and_requests_have_separate_tables(self):
        change=self.make_change(booking=self.booking)
        self.client.force_login(self.admin)
        bookings=self.client.get(reverse('admin_booking_list'))
        self.assertEqual(bookings.context['active_tab'],'bookings')
        self.assertContains(bookings,'Change Requests')
        self.assertContains(bookings,'aria-label="1 requests need admin action"')
        self.assertNotContains(bookings,'data-request-id=')
        self.assertNotContains(bookings,'Send Final Quote')
        response=self.queue()
        self.assertContains(response,f'data-request-id="{change.pk}"')
        self.assertContains(response,'Review Request')
        self.assertNotContains(response,'id="filterForm"')
        self.assertNotContains(response,'Approve booking')
        self.assertEqual(response.context['change_summary']['active'],1)
        self.assertEqual(Booking.objects.count(),1)

    def test_active_scope_excludes_closed_history(self):
        states=('pending_review','quoted','awaiting_payment','manual_review','applied','rejected','withdrawn','expired')
        requests=[self.make_change(status) for status in states]
        response=self.queue()
        self.assertEqual(set(c.status for c in response.context['change_requests']),set(states[:4]))
        self.assertEqual(response.context['change_summary']['active'],4)
        self.assertEqual(response.context['change_summary']['history'],4)
        self.assertEqual(response.context['change_summary']['needs_review'],2)
        history=self.queue(scope='history')
        self.assertEqual(set(c.status for c in history.context['change_requests']),set(states[4:]))
        self.assertNotContains(history,'Review Request')
        self.assertContains(history,'View Request')

    def test_submitted_change_payment_is_counted_as_an_admin_action(self):
        change=self.make_change('awaiting_payment')
        Payment.objects.create(booking=change.booking,change_request=change,applied_to_booking=False,
            payment_method='gcash',amount=2000,transaction_ref='queue-receipt')
        response=self.queue()
        self.assertEqual(response.context['change_summary']['needs_review'],1)
        self.assertContains(response,'Payment to Verify')
        self.assertEqual(response.context['change_summary']['waiting'],0)

    def test_unpaid_online_checkout_does_not_raise_admin_badge(self):
        change=self.make_change('awaiting_payment')
        Payment.objects.create(booking=change.booking,change_request=change,applied_to_booking=False,
            payment_method='paymongo_gcash',amount=2000,transaction_ref='queue-unpaid',paymongo_checkout_session_id='cs_unpaid')
        response=self.queue()
        self.assertEqual(response.context['change_summary']['needs_review'],0)
        self.assertEqual(response.context['change_summary']['waiting'],1)
        self.assertNotContains(response,'Payment to Verify')

    def test_requests_needing_action_sort_ahead_of_waiting_requests(self):
        pending=self.make_change()
        newer=self.make_change('quoted')
        BookingChangeRequest.objects.filter(pk=newer.pk).update(created_at=self.now+timedelta(minutes=1))
        response=self.queue()
        self.assertEqual(response.context['change_requests'][0].pk,pending.pk)

    def test_search_status_and_booking_filter_work_independently(self):
        target=self.make_change('quoted',booking=self.booking,reason='Move the celebration upstairs')
        other=self.make_change('pending_review')
        for query in ({'booking_id':self.booking.pk},{'request_search':'upstairs'},
                      {'request_search':f'#{target.pk}'},{'request_status':'quoted'}):
            response=self.queue(**query)
            self.assertContains(response,f'data-request-id="{target.pk}"')
            if query.get('request_search') != f'#{target.pk}' or other.booking_id != target.pk:
                self.assertNotContains(response,f'data-request-id="{other.pk}"')
        response=self.queue(request_search='& nobody <script>')
        self.assertContains(response,'No matching requests')
        self.assertNotContains(response,'<script>"')

    def test_pagination_and_return_link_preserve_filters(self):
        for index in range(12):self.make_change(reason=f'Keep & check {index}')
        response=self.queue(request_search='Keep & check',request_status='pending_review',request_page='2')
        self.assertEqual(response.context['change_requests'].number,2)
        self.assertEqual(len(response.context['change_requests']),4)
        previous=parse_qs(urlsplit(response.context['request_previous_url']).query)
        self.assertEqual(previous['request_search'],['Keep & check'])
        self.assertEqual(previous['request_status'],['pending_review'])
        self.assertEqual(previous['tab'],['requests'])
        links=response.context['request_page_links']
        self.assertEqual([link['label'] for link in links],[1,2])
        self.assertTrue(links[1]['current'])
        self.assertEqual(parse_qs(urlsplit(links[0]['url']).query)['request_search'],['Keep & check'])
        self.assertContains(response,'aria-label="Page 2">2</span>')
        self.assertNotContains(response,'Apply filters')
        self.assertContains(response,'id="requestResults"')
        change=response.context['change_requests'][0]
        review=self.client.get(change.review_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(review.status_code,200)
        self.assertIn('request_page=2',review.context['return_to'])
        self.assertIn('Keep+%26+check',review.context['return_to'])

    def test_empty_states_and_invalid_filters_are_safe(self):
        for params,text in (({},'No active change requests'),({'scope':'history'},'No request history yet'),
                            ({'request_search':'missing'},'No matching requests')):
            self.assertContains(self.queue(**params),text)
        response=self.queue(scope='invalid',request_status='applied',request_page='not-a-page',booking_id='invalid')
        self.assertEqual(response.context['request_scope'],'active')
        self.assertEqual(response.context['request_status'],'')
        self.assertEqual(response.status_code,200)

    def test_focused_review_shows_specific_historical_request(self):
        old=self.make_change('withdrawn',booking=self.booking,reason='Old request to keep in history')
        current=self.make_change(booking=self.booking,reason='Different newer request')
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_change_detail',args=[old.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.context['change_request'].pk,old.pk)
        self.assertContains(response,'Old request to keep in history')
        self.assertNotContains(response,'Different newer request')
        self.assertNotContains(response,'Send Final Quote')
        self.assertNotContains(response,'Decline Change Request')
        self.assertNotContains(response,'Manual Logistics Fee')
        self.assertNotContains(response,'Upload &amp; Send to Customer')
        self.assertContains(response,'Estimated revised total')
        self.assertEqual(response['Cache-Control'],'private, no-store')

    def test_booking_detail_only_links_to_request_review(self):
        change=self.make_change(booking=self.booking)
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_detail',args=[self.booking.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response,reverse('admin_booking_change_detail',args=[change.pk]))
        self.assertNotContains(response,'id="change_admin_notes"')
        self.assertNotContains(response,'Send Final Quote')
        self.assertContains(response,'Manual Logistics Fee')

    def test_booking_callout_prefers_active_request_over_more_recent_history(self):
        active=self.make_change(booking=self.booking)
        self.make_change('withdrawn',booking=self.booking)
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_detail',args=[self.booking.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.context['change_request'].pk,active.pk)
        customer=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertEqual(customer.status_code,403)
        self.client.force_login(self.user)
        customer=self.client.get(reverse('booking_modal_content',args=[self.booking.pk]))
        self.assertEqual(customer.context['change_request'].pk,active.pk)

    def test_quote_submit_stays_on_request_review_and_keeps_list_context(self):
        change=self.submit(package_type='Package B')
        self.client.force_login(self.admin)
        back=f"{reverse('admin_booking_list')}?tab=requests&request_search=change&request_page=2"
        response=self.client.post(reverse('admin_booking_change_action',args=[self.booking.pk,change.pk,'quote']),{'return_to':back})
        self.assertEqual(urlsplit(response.url).path,reverse('admin_booking_change_detail',args=[change.pk]))
        self.assertEqual(parse_qs(urlsplit(response.url).query)['return_to'],[back])
        change.refresh_from_db();self.assertEqual(change.status,'quoted')
        self.assertEqual(self.booking.package_type,'Package A')

    def test_external_or_malformed_return_url_cannot_redirect_offsite(self):
        change=self.make_change(booking=self.booking)
        self.client.force_login(self.admin)
        for value in ('https://example.com/staff/bookings/','//example.com/staff/bookings/','//[bad','/other-page/'):
            response=self.client.get(reverse('admin_booking_change_detail',args=[change.pk]),{'return_to':value}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['return_to'],f"{reverse('admin_booking_list')}?tab=requests&scope=active")

    def test_notification_opens_exact_request_even_when_another_request_is_newer(self):
        old=self.make_change('withdrawn',booking=self.booking)
        self.make_change(booking=self.booking)
        self.assertEqual(_admin_notif_target_url('event',f'Booking change request #{old.pk} for Booking #{self.booking.pk}: quote expired',self.booking),f"{reverse('admin_booking_list')}?tab=requests&open_change={old.pk}")
        self.assertEqual(_admin_notif_target_url('event',f'Change request #{old.pk} has submitted payment',self.booking),f"{reverse('admin_booking_list')}?tab=requests&open_change={old.pk}")

    def test_historical_paid_amount_does_not_change_with_later_payments(self):
        change=self.make_change('applied',booking=self.booking,quoted_total=5000,quote={'verified_paid_at_review':'6000','non_refundable_excess':'1000'})
        Payment.objects.create(booking=self.booking,amount=3000,payment_status='verified',payment_method='gcash',transaction_ref='later-unrelated-payment')
        self.client.force_login(self.admin)
        response=self.client.get(reverse('admin_booking_change_detail',args=[change.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.context['change_verified_paid'],Decimal('6000'))
        self.assertEqual(response.context['change_excess_payment'],Decimal('1000'))
        self.assertContains(response,'Verified payments when quoted')

    def test_customers_cannot_access_the_admin_queue_or_review(self):
        change=self.make_change(booking=self.booking)
        for user in (self.user,self.other):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('admin_booking_list'),{'tab':'requests'}).status_code,403)
            self.assertEqual(self.client.get(reverse('admin_booking_change_detail',args=[change.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('admin_booking_change_detail',args=[change.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,302)

    def test_unknown_request_is_404_and_review_is_read_only_get(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin_booking_change_detail',args=[999999])).status_code,404)
        change=self.make_change(booking=self.booking)
        self.assertEqual(self.client.post(reverse('admin_booking_change_detail',args=[change.pk])).status_code,405)
