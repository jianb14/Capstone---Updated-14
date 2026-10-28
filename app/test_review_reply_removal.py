"""Regression coverage for public replies and the new review details modal."""
from datetime import date, time

from django.test import Client, TestCase
from django.urls import resolve, reverse

from .models import Booking, Review, ReviewReply, User


class ReviewReplyRemovalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@test.com",
            password="pass12345",
            role="admin",
        )
        self.customer = User.objects.create_user(
            username="cust",
            email="cust@test.com",
            password="pass12345",
            role="customer",
        )
        self.booking = Booking.objects.create(
            user=self.customer,
            event_date=date(2099, 6, 15),
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Test Venue",
            package_type="Package A",
            total_price=5000,
            status="completed",
        )
        self.review = Review.objects.create(
            user=self.customer,
            booking=self.booking,
            rating=5,
            comment="Great service!",
        )

    def _create_reply(self):
        return ReviewReply.objects.create(
            review=self.review,
            admin=self.admin,
            reply_text="Thank you for celebrating with us!",
        )

    def _delete_url(self):
        return reverse("admin_review_delete_reply", args=[self.review.id])

    def _detail_url(self):
        return reverse("admin_review_detail", args=[self.review.id])

    def test_delete_url_resolves(self):
        match = resolve(f"/staff/reviews/{self.review.id}/reply/delete/")
        self.assertEqual(match.url_name, "admin_review_delete_reply")
        self.assertEqual(
            self._delete_url(),
            f"/staff/reviews/{self.review.id}/reply/delete/",
        )

    def test_admin_can_delete_reply(self):
        self._create_reply()
        self.client.force_login(self.admin)
        response = self.client.post(self._delete_url())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(self._detail_url()))
        self.assertFalse(
            ReviewReply.objects.filter(review=self.review).exists()
        )

    def test_retired_role_cannot_delete_reply(self):
        legacy = User.objects.create_user(
            username="retired-role",
            email="legacy@test.com",
            password="pass12345",
            role="staff",
        )
        self._create_reply()
        self.client.force_login(legacy)
        response = self.client.post(self._delete_url())
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            ReviewReply.objects.filter(review=self.review).exists()
        )

    def test_customer_cannot_delete_reply(self):
        self._create_reply()
        self.client.force_login(self.customer)
        response = self.client.post(self._delete_url())
        self.assertEqual(response.status_code, 403)
        # Hindi dapat mabura ang reply
        self.assertTrue(
            ReviewReply.objects.filter(review=self.review).exists()
        )

    def test_anonymous_redirected_to_login(self):
        response = self.client.post(self._delete_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_get_not_allowed(self):
        self._create_reply()
        self.client.force_login(self.admin)
        response = self.client.get(self._delete_url())
        self.assertEqual(response.status_code, 405)
        self.assertTrue(
            ReviewReply.objects.filter(review=self.review).exists()
        )

    def test_delete_without_reply_redirects_without_crash(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._delete_url())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(self._detail_url()))

    def test_delete_nonexistent_review_404(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_review_delete_reply", args=[999999])
        )
        self.assertEqual(response.status_code, 404)

    def test_details_modal_shows_remove_only_when_reply_exists(self):
        self.client.force_login(self.admin)
        response = self.client.get(self._detail_url(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Post Reply', response.json()['html'])
        self.assertNotIn('Remove Reply', response.json()['html'])
        self._create_reply()
        response = self.client.get(self._detail_url(), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertIn('Update Reply', response.json()['html'])
        self.assertIn('Remove Reply', response.json()['html'])
        self.assertIn('formnovalidate', response.json()['html'])
        self.assertIn(self._delete_url(), response.json()['html'])

    def test_notification_detail_link_keeps_full_page_fallback(self):
        self._create_reply()
        self.client.force_login(self.admin)
        response = self.client.get(self._detail_url())
        self.assertContains(response, 'reviewDetailModal')
        self.assertContains(response, 'Remove Reply')
        self.assertContains(response, 'Update Reply')
        self.assertContains(response, f'data-initial-review="{self.review.pk}"')
