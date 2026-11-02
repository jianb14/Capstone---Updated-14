"""Every application page family loads the shared skeleton assets, including auth."""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import User


@override_settings(REQUEST_RATE_LIMITING_ENABLED=False)
class SkeletonPageCoverageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(username='skeleton-customer', role='customer', email_verified=True)
        cls.admin = User.objects.create_user(username='skeleton-admin', role='admin', email_verified=True)

    def assert_skeleton_page(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'css/skeleton.css', count=1)
        self.assertContains(response, 'js/skeleton.js', count=1)
        self.assertContains(response, 'data-skeleton-page')
        # Loading is opt-in JavaScript; server HTML stays accessible without it.
        self.assertNotContains(response, 'class="site-loading-replace"')

    def test_public_and_auth_routes(self):
        for name in ('home', 'about', 'services', 'package', 'gallery', 'reviews', 'guidelines',
                     'terms_conditions', 'data_privacy', 'login', 'register', 'forgot_password', 'resend_verification'):
            with self.subTest(route=name):
                self.assert_skeleton_page(self.client.get(reverse(name)))

    def test_customer_routes_keep_the_sidebar_outside_the_loading_region(self):
        self.client.force_login(self.customer)
        for name in ('customer_profile', 'my_profile', 'my_payments', 'my_reviews', 'report_concern',
                     'my_designs', 'select_design_type', 'booking_page'):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assert_skeleton_page(response)
                if name in ('customer_profile', 'my_profile', 'my_payments', 'my_reviews', 'report_concern'):
                    self.assertContains(response, 'id="sitePageContent" >')
                    self.assertContains(response, 'class="account-content" data-skeleton-page')

    def test_admin_routes(self):
        self.client.force_login(self.admin)
        names = ('dashboard', 'admin_analytics', 'admin_calendar', 'admin_booking_list', 'admin_payment_list',
                 'admin_user_list', 'admin_reviews', 'admin_concerns', 'admin_audit_log', 'admin_package_list',
                 'admin_gallery', 'admin_canvas_assets', 'admin_home_content', 'admin_about_content',
                 'admin_guidelines_content', 'admin_service_content', 'admin_site_settings', 'admin_profile',
                 'ai_health', 'admin_chat_inbox')
        for name in names:
            with self.subTest(route=name):
                self.assert_skeleton_page(self.client.get(reverse(name)))

    def test_standalone_verification_error_and_invitation_templates(self):
        request = RequestFactory().get('/verify-account/')
        request.user = self.customer
        for name in ('verify_otp', 'verify_email_link', 'change_signup_email'):
            with self.subTest(template=name):
                html = render_to_string(f'auth/{name}.html', {'digits': range(1, 7)}, request=request)
                self.assertIn('data-skeleton-page', html)
                self.assertEqual(html.count('js/skeleton.js'), 1)
                self.assertLess(html.index('<!doctype html>'), html.index('js/skeleton.js'))
        for template in ('errors/request_limit.html', 'admin/security/accept_invitation.html'):
            with self.subTest(template=template):
                html = render_to_string(template, {}, request=request)
                self.assertIn('js/skeleton.js', html)
                self.assertIn('data-skeleton-page', html)

    def test_every_browser_template_inherits_or_includes_the_shared_assets(self):
        root = Path(settings.BASE_DIR) / 'app/templates'
        # Walk inheritance, including detail/editor templates that need record fixtures.
        import re
        def covered(path, seen=None):
            seen = set() if seen is None else seen
            if path in seen:
                return False
            seen.add(path)
            source = path.read_text(encoding='utf-8')
            if 'components/skeleton_assets.html' in source or 'components/auth_presentation_assets.html' in source:
                return True
            parent = re.search(r"{%\s*extends\s+['\"]([^'\"]+)['\"]", source)
            return bool(parent and covered(root / parent.group(1), seen))
        for folder in ('admin', 'client', 'auth'):
            for path in (root / folder).rglob('*.html'):
                source = path.read_text(encoding='utf-8')
                if '{% extends' in source or '<!doctype' in source.lower() or folder == 'auth':
                    if path.name == 'analytics_pdf_template.html':
                        continue
                    with self.subTest(template=str(path.relative_to(root))):
                        self.assertTrue(covered(path))
