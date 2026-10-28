"""Review workspace reporting, async actions, authorization and feature capacity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import time
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Booking, Review, ReviewReply, User
from .review_management import build_review_context, review_summary


def fixture():
    admin = User.objects.create_user(username='review-admin', role='admin', email_verified=True)
    customer = User.objects.create_user(username='review-customer', first_name='Jamie', last_name='Rivera',
        email='jamie@example.com', role='customer', email_verified=True)
    booking = Booking.objects.create(user=customer, event_date=timezone.localdate(), event_time=time(9),
        event_type='Birthday', event_location='Test Venue', package_type='Package 1-A', total_price=4000, status='completed')
    return admin, customer, booking


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class AdminReviewTests(TestCase):
    def setUp(self):
        self.admin, self.customer, self.booking = fixture()
        self.review = self.add_review()
        self.client.force_login(self.admin)
        self.ajax = {'HTTP_X_REQUESTED_WITH':'XMLHttpRequest'}

    def add_review(self, **kwargs):
        return Review.objects.create(user=self.customer, booking=self.booking, **{'rating':5, 'comment':'Beautiful setup!', **kwargs})

    def url(self, name='admin_reviews', review=None):
        return reverse(name, args=[(review or self.review).pk] if name != 'admin_reviews' else [])

    def test_summary_valid_ratings_and_global_scope(self):
        self.add_review(rating=3, is_testimonial=True); self.add_review(rating=0)
        summary = review_summary()
        self.assertEqual(summary['total_reviews'], 3); self.assertEqual(summary['avg_rating'], 4)
        self.assertEqual(summary['rated_count'], 2); self.assertEqual(summary['unrated_count'], 1)
        self.assertEqual(summary['featured_count'], 1)
        self.assertEqual([row['pct'] for row in summary['rating_distribution']], [50,0,50,0,0])
        context = build_review_context({'rating':'3'})
        self.assertEqual(context['reviews'].paginator.count, 1); self.assertEqual(context['total_reviews'], 3)

    def test_no_fake_rating_in_empty_workspace(self):
        Review.objects.all().delete()
        response=self.client.get(self.url())
        self.assertContains(response,'No reviews yet'); self.assertIsNone(response.context['avg_rating'])
        self.assertNotContains(response,'<table class="ac-table rv-table">')
        self.assertNotContains(response,'data-list-footer')

    def test_search_matches_full_name_email_comment_event_setup_and_review_id(self):
        for search in ('Jamie Rivera','jamie@example.com','Beautiful setup','Birthday','Package 1-A',f'#REV-{self.review.pk}'):
            with self.subTest(search=search):
                self.assertEqual(list(build_review_context({'search':search})['reviews']), [self.review])
        response = self.client.get(self.url(), {'search':'<script>alert(1)</script>'}, **self.ajax)
        self.assertIn('No matching reviews', response.json()['html']); self.assertNotIn('<thead>', response.json()['html'])

    def test_pagination_is_stable_bounded_and_clamps_invalid_pages(self):
        for index in range(36): self.add_review(rating=index % 5 + 1)
        for value, size in (('',8),('4',4),('8',8),('999',8),('-1',8),('bad',8)):
            context=build_review_context({'per_page':value})
            self.assertEqual(len(context['reviews']), size)
        first=build_review_context({})['reviews']; second=build_review_context({'page':'2'})['reviews']
        self.assertFalse(set(first.object_list)&set(second.object_list))
        self.assertEqual(build_review_context({'page':'999'})['reviews'].number, 5)
        self.assertEqual(build_review_context({'page':'invalid'})['reviews'].number, 1)
        response=self.client.get(self.url(), {'page':'2'}, **self.ajax)
        self.assertEqual(response.status_code,200); self.assertEqual(response.json()['page'],2)
        self.assertEqual(response.json()['html'].count('data-review-row='),8)
        more_pages=self.client.get(self.url(), {'page':'2','per_page':'4'}, **self.ajax)
        self.assertIn('account-page-ellipsis',more_pages.json()['html'])
        self.assertEqual(response['Cache-Control'],'no-store')

    def test_combined_rating_and_testimonial_filter_and_sort(self):
        low=self.add_review(rating=2,is_testimonial=True); self.add_review(rating=2)
        context=build_review_context({'rating':'2','featured':'featured','sort':'rating'})
        self.assertEqual(list(context['reviews']),[low]); self.assertEqual(context['featured_count'],1)
        self.assertEqual(list(build_review_context({'sort':'rating'})['reviews'])[0],low)
        fallback=build_review_context({'rating':'999','sort':'user__password','featured':'invalid'})
        self.assertEqual(fallback['rating_filter'],''); self.assertEqual(fallback['sort_filter'],'-created_at')
        self.assertEqual(fallback['reviews'].paginator.count,3)

    def test_admin_details_escape_text_and_include_booking(self):
        self.review.comment='<script>alert("unsafe")</script>'+'longword'*100
        self.review.save(update_fields=['comment'])
        response=self.client.get(self.url('admin_review_detail'),**self.ajax)
        self.assertEqual(response.status_code,200); data=response.json()
        self.assertEqual(data['id'],self.review.pk)
        self.assertIn('&lt;script&gt;',data['html']); self.assertNotIn('<script>',data['html'])
        self.assertIn('Package 1-A',data['html']); self.assertIn('Birthday',data['html'])
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertEqual(self.client.get(reverse('admin_review_detail',args=[999999]),**self.ajax).status_code,404)

    def test_only_admin_can_read_or_write_reviews(self):
        self.client.force_login(self.customer)
        for name in ('admin_reviews','admin_review_detail'):
            self.assertEqual(self.client.get(self.url(name),**self.ajax).status_code,403)
        for name in ('admin_review_reply','admin_review_delete_reply','admin_review_toggle_testimonial'):
            self.assertEqual(self.client.post(self.url(name),{'reply_text':'wrong','is_testimonial':'1'},**self.ajax).status_code,403)
        self.assertFalse(ReviewReply.objects.exists()); self.review.refresh_from_db(); self.assertFalse(self.review.is_testimonial)
        self.client.logout(); self.assertEqual(self.client.get(self.url()).status_code,302)

    def test_all_review_writes_are_post_only_and_csrf_protected(self):
        csrf_client=Client(enforce_csrf_checks=True);csrf_client.force_login(self.admin)
        for name in ('admin_review_reply','admin_review_delete_reply','admin_review_toggle_testimonial'):
            self.assertEqual(self.client.get(self.url(name),**self.ajax).status_code,405)
            self.assertEqual(csrf_client.post(self.url(name),**self.ajax).status_code,403)

    def test_reply_validation_create_update_and_removal_are_async(self):
        url=self.url('admin_review_reply')
        for text in ('   ','x'*2001):
            self.assertEqual(self.client.post(url,{'reply_text':text},**self.ajax).status_code,400)
        self.assertFalse(ReviewReply.objects.exists())
        for text in ('Thank you!','Happy to help with your next celebration.'):
            response=self.client.post(url,{'reply_text':text},**self.ajax)
            self.assertEqual(response.status_code,200); self.assertEqual(ReviewReply.objects.get().reply_text,text)
            self.assertIn('Remove Reply',response.json()['html'])
        response=self.client.post(self.url('admin_review_delete_reply'),**self.ajax)
        self.assertEqual(response.status_code,200);self.assertFalse(ReviewReply.objects.exists())
        self.assertIn('Post Reply',response.json()['html']);self.assertNotIn('Remove Reply',response.json()['html'])
        self.assertEqual(self.client.post(self.url('admin_review_delete_reply'),**self.ajax).status_code,200)

    def test_feature_limit_idempotency_unfeature_and_audit(self):
        for _ in range(4):self.add_review(is_testimonial=True)
        url=self.url('admin_review_toggle_testimonial')
        response=self.client.post(url,{'is_testimonial':'1'},**self.ajax)
        self.assertEqual(response.status_code,409);self.assertIn('4 testimonial slots',response.json()['message'])
        other=Review.objects.filter(is_testimonial=True).first()
        self.client.post(self.url('admin_review_toggle_testimonial',other),{'is_testimonial':'0'},**self.ajax)
        for _ in range(2):
            response=self.client.post(url,{'is_testimonial':'1'},**self.ajax)
            self.assertEqual(response.status_code,200)
        self.assertEqual(Review.objects.filter(is_testimonial=True).count(),4)
        self.assertEqual(AuditLog.objects.filter(action=f'Review #{self.review.pk} featured as testimonial.').count(),1)
        self.assertEqual(self.client.post(url,{'is_testimonial':'wrong'},**self.ajax).status_code,400)


@skipUnless(connection.vendor=='postgresql','Feature capacity concurrency check uses PostgreSQL row locks')
@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class ReviewFeatureConcurrencyTests(TransactionTestCase):
    def test_two_admins_competing_for_last_slot_cannot_exceed_four(self):
        admin, customer, booking=fixture()
        other=User.objects.create_user(username='second-review-admin',role='admin',email_verified=True)
        for _ in range(3):Review.objects.create(user=customer,booking=booking,rating=5,comment='Featured',is_testimonial=True)
        targets=[Review.objects.create(user=customer,booking=booking,rating=5,comment='Candidate') for _ in range(2)]
        clients=[Client(),Client()]
        for client,user in zip(clients,[admin,other]):client.force_login(user)
        from threading import Barrier
        barrier=Barrier(2)
        def submit(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return clients[index].post(reverse('admin_review_toggle_testimonial',args=[targets[index].pk]),
                    {'is_testimonial':'1'},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(statuses),[200,409]);self.assertEqual(Review.objects.filter(is_testimonial=True).count(),4)
