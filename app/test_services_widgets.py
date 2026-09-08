"""Tests for the Services page interactive widgets and dynamic content."""
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from .models import Service, User


class ServicesPageWidgetsTests(TestCase):
    def setUp(self):
        self.client = Client()
        Service.objects.create(
            title="Birthday Balloon Styling",
            description="Fun setups for birthdays.",
            features="Balloon arch\nTable centerpieces\nPhoto booth backdrop",
            best_for="Kids parties and milestones",
            display_order=1,
        )
        Service.objects.create(
            title="Wedding Balloon Installations",
            description="Elegant wedding styling.",
            features="Ceremony arches\nDance floor canopy",
            best_for="Weddings and receptions",
            display_order=2,
        )

    def test_services_page_renders_all_sections(self):
        response = self.client.get("/services/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("services-tools", body)
        self.assertIn("style-quiz", body)
        self.assertIn("price-estimator", body)
        self.assertIn("date-check", body)
        self.assertIn("services-comparison", body)
        self.assertIn("Which Service Is Right for You?", body)
        self.assertIn("services_widgets.js", body)
        self.assertIn("services-widget-data", body)

    def test_hero_matches_about_page_style(self):
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        self.assertIn('class="about-hero"', body)
        self.assertIn("about-tagline", body)
        self.assertIn('class="scroll-down"', body)
        self.assertIn("#services-list", body)
        self.assertIn('id="services-list"', body)

    def test_hero_label_default_and_from_db(self):
        # Default label kapag walang ServiceContent row
        response = self.client.get("/services/")
        self.assertContains(response, "Balloorina Services")

        # Label mula sa DB kapag may existing row
        from .models import ServiceContent

        ServiceContent.objects.create(
            hero_label="Custom Label",
            hero_title="Custom Title",
        )
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        self.assertIn("Custom Label", body)
        self.assertIn("Custom Title", body)

    def test_tools_section_is_below_services_and_comparison(self):
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        services_pos = body.find('id="services-list"')
        comparison_pos = body.find("services-comparison")
        tools_pos = body.find("services-tools")
        self.assertLess(services_pos, tools_pos)
        self.assertLess(comparison_pos, tools_pos)

    def test_dynamic_service_features_render(self):
        # Ang features ay hindi na nag-aappear bilang bulleted list sa service
        # detail sections — puro na lang sa comparison table ("Key Inclusions").
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        detail_pos = body.find('id="services-list"')
        comparison_pos = body.find("services-comparison")
        self.assertNotIn('class="service-features"', body)
        # Features are still visible in the comparison table
        self.assertIn("Balloon arch", body[comparison_pos:])
        self.assertIn("Dance floor canopy", body[comparison_pos:])
        # Walang feature bullets sa loob ng detail sections
        self.assertNotIn("service-features", body[detail_pos:comparison_pos])

    def test_service_items_have_scroll_reveal_hooks(self):
        # Ang services page ay kasama na sa staggered scroll reveal system
        js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "theme-toggle.js"
        js = js_path.read_text(encoding="utf-8")
        self.assertIn("'home', 'about', 'services'", js)
        self.assertIn(".service-item .service-content > *", js)
        self.assertIn(".service-item .service-image", js)
        self.assertIn(".services-tools-inner > .tool-card", js)

    def test_comparison_table_shows_best_for(self):
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        self.assertIn("Kids parties and milestones", body)
        self.assertIn("Weddings and receptions", body)
        self.assertIn("Birthday Balloon Styling", body)

    def test_comparison_table_hidden_with_fewer_than_two_services(self):
        Service.objects.all().delete()
        Service.objects.create(title="Only One", description="Desc")
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        self.assertNotIn("services-comparison", body)
        self.assertIn("Only One", body)

    def test_estimator_data_exposed_as_json(self):
        response = self.client.get("/services/")
        # json_script wraps data in a <script id="services-widget-data"> tag
        self.assertContains(response, 'id="services-widget-data"')


class DateAvailabilityApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("check_date_availability")

    def test_requires_date(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_rejects_past_date(self):
        response = self.client.get(self.url + "?date=2000-01-01")
        self.assertEqual(response.status_code, 400)
        self.assertIn("future", response.json()["error"])

    def test_future_date_available(self):
        response = self.client.get(self.url + "?date=2099-01-15")
        data = response.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["available"])
        self.assertEqual(len(data["suggestions"]), 3)

    def test_booked_date_reports_taken_with_suggestions(self):
        from django.utils import timezone

        from .models import Booking

        customer = User.objects.create_user(
            username="booker", email="booker@test.com", password="pass12345", role="customer"
        )
        Booking.objects.create(
            user=customer,
            event_date=timezone.localdate() + timezone.timedelta(days=10),
            event_time=timezone.datetime(2020, 1, 1, 10, 0).time(),
            package_type="Package A",
            payment_status="pending",
            total_price=100,
            status="confirmed",
        )
        target = (timezone.localdate() + timezone.timedelta(days=10)).isoformat()
        response = self.client.get(self.url + "?date=" + target)
        data = response.json()
        self.assertFalse(data["available"])
        self.assertEqual(len(data["suggestions"]), 3)
        self.assertNotIn(target, data["suggestions"])


class ThemeQuizApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("theme_quiz_api")

    def test_anonymous_gets_403(self):
        response = self.client.post(
            self.url,
            data='{"event_type": "Birthday", "vibe": "Fun"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_authenticated_missing_fields_gets_400(self):
        user = User.objects.create_user(
            username="customer1", email="c@test.com", password="pass12345", role="customer"
        )
        self.client.force_login(user)
        response = self.client.post(
            self.url,
            data='{"event_type": "Birthday"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("vibe", response.json()["error"])