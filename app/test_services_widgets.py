"""Tests for the Services page interactive widgets and dynamic content."""
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from .models import AdditionalOnly, AddOn, Package, Service, User


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
        # Default label kapag walang ServiceContent row (see _SERVICE_DEFAULTS)
        response = self.client.get("/services/")
        self.assertContains(response, "Balloorina Event Styling")

        # Label mula sa DB kapag may existing row
        # (tanggalin muna ang auto-seeded row galing sa unang GET)
        from .models import ServiceContent

        ServiceContent.objects.all().delete()
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

    def test_quiz_budget_field_removed(self):
        # The AI quiz no longer asks for a budget range.
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        self.assertNotIn("Budget Range", body)
        self.assertNotIn("quizBudget", body)

    def test_estimator_uses_custom_select_dropdowns(self):
        # The pretty native selects were replaced with the booking page's
        # custom-select dropdown design.
        Package.objects.create(name="Package A", features="Arch", price=10000)
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        self.assertIn("custom-select-container", body)
        self.assertIn('id="estimatorPackage"', body)

    def test_estimator_addons_single_select_and_welcome_stand_present(self):
        Package.objects.create(name="Package A", features="Arch", price=10000)
        AddOn.objects.create(
            name="Entrance A", features="Arch", price=3499, solo_price=4999
        )
        AdditionalOnly.objects.create(
            name="Welcome Stand", features="Stand", price=1500
        )
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        # Single-select add-on (radio) instead of multiple checkboxes.
        self.assertIn('name="estimatorAddon"', body)
        self.assertIn('type="radio"', body)
        # Welcome Stand section is now part of the estimator.
        self.assertIn('id="estimatorAdditionals"', body)
        self.assertIn('name="estimatorAdditional"', body)
        self.assertIn("Welcome Stand", body)

    def test_widget_data_exposes_additionals(self):
        Package.objects.create(name="Package A", features="Arch", price=10000)
        AdditionalOnly.objects.create(
            name="Welcome Stand", features="Stand", price=1500
        )
        response = self.client.get("/services/")
        data = response.context["services_widget_data"]
        self.assertEqual(len(data["additionals"]), 1)
        self.assertEqual(data["additionals"][0]["name"], "Welcome Stand")
        self.assertEqual(data["additionals"][0]["price"], "1500.00")

    def test_tool_badges_are_label_only(self):
        # Badge = plain text na lang: walang icon, border, o background.
        response = self.client.get("/services/")
        body = response.content.decode("utf-8")
        for label in ("AI-Powered", "Instant Estimate", "Live Availability"):
            self.assertIn(label, body)

        self.assertNotIn("fa-regular fa-lightbulb\"></i>AI-Powered", body)
        self.assertNotIn("fa-regular fa-credit-card\"></i>Instant Estimate", body)
        self.assertNotIn("fa-regular fa-calendar\"></i>Live Availability", body)

        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        badge_block = css.split(".tool-badge {")[1].split("}")[0]
        self.assertNotIn("border", badge_block)
        self.assertNotIn("background", badge_block)
        self.assertNotIn("<i", badge_block)
        # Walang na ring icon rule para sa badge.
        self.assertNotIn(".tool-badge i {", css)

        # Generated "Your AI Theme Suggestion" heading still uses a regular icon.
        js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "services_widgets.js"
        js = js_path.read_text(encoding="utf-8")
        self.assertNotIn("fa-solid fa-wand-magic-sparkles", js)
        self.assertIn("fa-regular fa-lightbulb", js)

    def test_tool_cards_match_package_card_background(self):
        # Cards should use the same bg as the Packages page cards.
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn("background: var(--pkg-card)", css)
        self.assertIn("[data-theme=\"light\"] .tool-card {\n    background: #f9f9fa;", css)

    def test_uniform_field_and_button_heights(self):
        # Inputs and the custom select must share one height, and all tool
        # buttons must be the same size.
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn(".tool-field .custom-select-trigger {\n    height: 44px;", css)
        self.assertIn(".services-tools .btn {\n    width: 100%;\n    height: 40px;", css)

    def test_widget_polish_no_heavy_shadows_or_white_borders(self):
        # Minimal dropdown shadow and subtle success borders (not near-white in
        # dark mode).
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn("box-shadow: 0 6px 16px rgba(0, 0, 0, 0.22);", css)
        self.assertNotIn("box-shadow: 0 12px 30px rgba(0, 0, 0, 0.45);", css)
        self.assertIn(
            ".availability-open {\n    border-color: rgba(255, 255, 255, 0.16);", css
        )
        self.assertIn(".quiz-result-success {\n    border-color: rgba(255, 255, 255, 0.16);", css)

    def test_addon_radio_and_label_are_center_aligned(self):
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        # Regression: `.tool-field label { display: block }` (0,1,1) ay
        # nanalo sa `.addon-check { display: flex }` (0,1,0) kaya na-stack
        # ang radio at label. Excluded na ang addon-check sa field caption.
        self.assertIn(".tool-field label:not(.addon-check) {", css)
        self.assertNotIn("\n.tool-field label {", css)
        row_block = css.split(".addon-check {")[1].split("}")[0]
        self.assertIn("display: flex;", row_block)
        self.assertIn("align-items: center;", row_block)
        # Radio: walang default margin ng browser, pinwerso sa gitna ng row.
        self.assertIn(".addon-check input {", css)
        radio_block = css.split(".addon-check input {")[1].split("}")[0]
        self.assertIn("align-self: center;", radio_block)
        self.assertIn("margin: 0;", radio_block)
        # Label: line-height pinareho sa row para eksaktong magkasalubong.
        label_block = css.split(".addon-check > span {")[1].split("}")[0]
        self.assertIn("align-items: center;", label_block)
        self.assertIn("line-height: 1.4;", label_block)

    def test_tools_section_padding_matches_other_sections(self):
        # Pareho ang padding ng .services-tools sa .services-detailed (8rem 5%).
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        tools_block = css.split(".services-tools {")[1].split("}")[0]
        self.assertIn("padding: 8rem 5%;", tools_block)
        detailed_block = css.split(".services-detailed {")[1].split("}")[0]
        self.assertIn("padding: 8rem 5%;", detailed_block)

    def test_service_image_placeholder_uses_minimal_shadow(self):
        # Kapag walang naka-attach na image, dapat minimal na shadow lang
        # (hindi yung malaking shadow na para sa tunay na larawan).
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn(".service-image:has(.service-image-placeholder) {", css)
        dark_block = css.split(".service-image:has(.service-image-placeholder) {")[1].split("}")[0]
        self.assertIn("box-shadow: none;", dark_block)

        self.assertIn(
            '[data-theme="light"] .service-image:has(.service-image-placeholder) {', css
        )
        light_block = css.split(
            '[data-theme="light"] .service-image:has(.service-image-placeholder) {'
        )[1].split("}")[0]
        self.assertIn("box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);", light_block)
        # Hindi na dapat kasama ang dating malaking shadow sa placeholder.
        self.assertNotIn("0 12px 32px rgba(0, 0, 0, 0.1);", light_block)
        # Parehong bg/border sa package card sa light mode (#f9f9fa / #e8e8ea)
        # — ang dating #eef0f3 ay masyadong gray.
        self.assertIn("background: #f9f9fa;", light_block)
        self.assertIn("border-color: #e8e8ea;", light_block)
        self.assertNotIn("#eef0f3", light_block)

        # Kapareho ng aktuwal na package card sa light mode.
        pkg_block = css.split('[data-theme="light"] .package-card {')[1].split("}")[0]
        self.assertIn("background: #f9f9fa;", pkg_block)
        self.assertIn("border: 1px solid #e8e8ea;", pkg_block)


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