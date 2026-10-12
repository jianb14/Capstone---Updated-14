"""Regression tests para sa admin Review Details page (/staff/reviews/<id>/view/).

Tatlong issue ang tinatakpan nito:
1. Remove admin reply — dati, pag nag-post ka ng reply, hindi mo na maaalis.
   Ngayon may `admin_review_delete_reply` view + Remove Reply button.
2. Meta icons (Submitted On / Event Type / Event Date) — dati may sariling
   brand color (asul #3b82f6, amber #f59e0b, purple #8b5cf6) na wala sa
   monochrome theme. Ngayon `color: inherit` na (sumusunod sa .meta-icon).
3. Light-mode divider — ang .meta-list ay `border-top: 1px solid var(--border)`
   kung saan --border: #222 (hindi nag-iiba sa light mode), kaya halos itim
   sa puting card. Ngayon may `[data-theme="light"] .meta-list` override na.
"""
from datetime import date, time
from pathlib import Path

from django.test import Client, TestCase
from django.urls import resolve, reverse

from .models import Booking, Review, ReviewReply, User

BASE_DIR = Path(__file__).resolve().parent.parent


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

    def test_staff_can_delete_reply(self):
        staff = User.objects.create_user(
            username="staff",
            email="staff@test.com",
            password="pass12345",
            role="staff",
        )
        self._create_reply()
        self.client.force_login(staff)
        response = self.client.post(self._delete_url())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
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

    def _template(self):
        return (
            BASE_DIR / "app" / "templates" / "admin" / "admin_review_detail.html"
        ).read_text(encoding="utf-8")

    def test_template_has_remove_button_with_formaction(self):
        template = self._template()
        self.assertIn("btn-remove-reply", template)
        self.assertIn("Remove Reply", template)
        self.assertIn("admin_review_delete_reply", template)
        self.assertIn("formaction=", template)
        # Walang required-validation ang textarea pag Remove ang pinindot
        self.assertIn("formnovalidate", template)
        # May confirm dialog bago mag-delete
        self.assertIn("return confirm(", template)
        # Magkatabi ang dalawang button sa kanan
        self.assertIn("reply-actions", template)

    def test_detail_page_shows_remove_button_when_reply_exists(self):
        self._create_reply()
        self.client.force_login(self.admin)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("Remove Reply", body)
        self.assertIn("Update Reply", body)

    def test_detail_page_hides_remove_button_without_reply(self):
        self.client.force_login(self.admin)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn("Remove Reply", body)
        self.assertIn("Post Reply", body)

    def test_template_cache_buster_bumped(self):
        self.assertIn(
            "css/admin_reviews.css' %}?v=20261012a", self._template()
        )

    def _css(self):
        return (
            BASE_DIR / "static" / "css" / "admin_reviews.css"
        ).read_text(encoding="utf-8")

    def test_meta_icons_are_monochrome(self):
        css = self._css()
        # Ang meta-icon rules ay hindi dapat may sariling brand colors
        for rule in (
            ".meta-icon i.fa-calendar-alt",
            ".meta-icon i.fa-glass-cheers",
            ".meta-icon i.fa-clock",
        ):
            self.assertIn(rule, css)
        block_start = css.index(".meta-icon i.fa-calendar-alt")
        block_end = css.index("}", block_start)
        block = css[block_start:block_end]
        self.assertNotIn("#3b82f6", block)
        self.assertNotIn("#f59e0b", block)
        self.assertNotIn("#8b5cf6", block)
        # Icons ay sumusunod sa .meta-icon color (monochrome)
        self.assertIn("color: inherit;", block)

    def test_light_mode_divider_is_light_gray(self):
        css = self._css()
        selector = '[data-theme="light"] .meta-list {'
        self.assertIn(selector, css)
        block = css.split(selector)[1].split("}")[0]
        self.assertIn("border-top-color: #e5e7eb", block)
        # Hindi dapat itim ang divider
        self.assertNotIn("#222", block)

    def test_dark_mode_divider_kept(self):
        # Ang .meta-list base rule ay nananatiling var(--border) sa dark
        css = self._css()
        self.assertIn("border-top: 1px solid var(--border);", css)

    def test_remove_button_styled_both_themes(self):
        css = self._css()
        self.assertIn(".btn-remove-reply {", css)
        self.assertIn(".btn-remove-reply:hover {", css)
        self.assertIn(".reply-actions {", css)
        selector = '[data-theme="light"] .btn-remove-reply {'
        self.assertIn(selector, css)
        block = css.split(selector)[1].split("}")[0]
        self.assertIn("background: #ffffff", block)
        self.assertIn("border-color: #d1d5db", block)

    def test_staticfiles_copy_in_sync(self):
        dist = (
            BASE_DIR / "staticfiles" / "css" / "admin_reviews.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".btn-remove-reply {", dist)
        self.assertIn('[data-theme="light"] .meta-list {', dist)
        self.assertIn("color: inherit;", dist)
