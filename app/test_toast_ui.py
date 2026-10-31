"""Client pages share local feedback assets; review ownership remains enforced."""
from pathlib import Path

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.auth.models import AnonymousUser

from .models import User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class ClientFeedbackRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='feedback-owner', email='feedback@example.com',
            role='customer', email_verified=True)

    def assert_feedback_assets(self, html):
        self.assertEqual(html.count('js/toast_helper.js'), 1)
        self.assertEqual(html.count('css/client_feedback.css'), 1)
        self.assertEqual(html.count('css/admin_feedback.css'), 1)
        self.assertNotIn('sweetalert', html.lower())
        self.assertNotIn('Swal.', html)

    def test_customer_pages_render_shared_feedback_once(self):
        self.client.force_login(self.user)
        for path in ('/', '/reviews/', '/my-reviews/', '/services/', '/booking/',
                     '/my-profile/', '/customer/', '/my-payments/', '/report-concern/', '/my-designs/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assert_feedback_assets(response.content.decode())

    def test_standalone_auth_pages_use_same_local_feedback(self):
        request = RequestFactory().get('/login/')
        request.user = AnonymousUser()
        for template in ('login', 'register', 'forgot_password', 'reset_password', 'resend_verification'):
            with self.subTest(template=template):
                self.assert_feedback_assets(render_to_string('auth/'+template+'.html', request=request))

    def test_client_templates_have_no_remaining_sweetalert_dependency(self):
        root = Path(__file__).resolve().parent / 'templates'
        for folder in ('client', 'auth'):
            for path in (root/folder).rglob('*.html'):
                with self.subTest(template=path.name):
                    source = path.read_text(encoding='utf-8')
                    self.assertNotIn('sweetalert', source.lower())
                    self.assertNotIn('Swal.', source)

class DeleteReviewViewTests(TestCase):
    """Sanity check sa server side ng delete_review (error body = JSON)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="toast_tester", password="pw", email="t@example.com"
        )
        self.other = User.objects.create_user(
            username="toast_other", password="pw", email="o@example.com"
        )
        self.client.force_login(self.user)

    def _create_review(self, user=None):
        from .models import Booking, Review

        booking, _ = Booking.objects.get_or_create(
            user=user or self.user,
            event_date="2030-01-01",
            defaults={
                "event_location": "Test Venue",
                "total_price": "1000.00",
                "status": "completed",
            },
        )
        return Review.objects.create(
            user=user or self.user,
            booking=booking,
            rating=5,
            comment="Test review para sa toast",
        )

    def test_delete_review_returns_json_success(self):
        review = self._create_review()
        response = self.client.post(f"/reviews/{review.id}/delete/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())

    def test_delete_other_users_review_is_not_found(self):
        review = self._create_review(user=self.other)
        response = self.client.post(f"/reviews/{review.id}/delete/")
        self.assertEqual(response.status_code, 404)
