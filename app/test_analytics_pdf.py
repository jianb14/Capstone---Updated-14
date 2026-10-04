"""Tests for the admin analytics PDF export, focused on the KPI section.

The KPI summary used to render as a grid of bordered "card" boxes
(``.summary-grid`` / ``.summary-box``), which looked out of place inside an
otherwise plain business report. It now renders as a regular ``table.data``
(Metric | Value) matching the other sections of the PDF (Status Breakdown,
Revenue by Event, ...).
"""
import io

from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from .models import User

try:  # pypdf is pulled in by xhtml2pdf (see requirements.txt)
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - optional at runtime
    PdfReader = None

TEMPLATE = "admin/analytics_pdf_template.html"

KPI_ROWS = [
    ("Total Bookings", "15"),
    ("Total Revenue", "PHP 11,598.00"),
    ("Completion Rate", "13.30%"),
    ("Cancellation Rate", "6.70%"),
    ("Avg. Booking Value", "PHP 5,799.00"),
    ("Active Customers", "6"),
    ("Completed", "2"),
    ("Cancelled", "1"),
]

CONTEXT = {
    "now": "October 03, 2026 02:02 PM",
    "start_date_str": "Sep 03, 2026",
    "end_date_str": "Oct 03, 2026",
    "selected_event_type": "All",
    "total_bookings": 15,
    "total_revenue": "11,598.00",
    "completion_rate": "13.30",
    "cancellation_rate": "6.70",
    "avg_booking_value": "5,799.00",
    "active_users": 6,
    "completed_count": 2,
    "cancelled_count": 1,
    "pending_approvals": 3,
    "action_queue_total": 3,
    "new_customers_count": 4,
    "returning_customers_count": 2,
    "new_customers_pct": "66.67",
    "returning_customers_pct": "33.33",
    "status_table": [],
    "revenue_by_event": [],
    "package_rows": [],
    "top_customers": [],
    "upcoming_deadline_bookings": [],
    "summary_notes": [],
}


class AnalyticsPdfKpiTests(TestCase):
    """Ang KPI section ay table na, hindi na card grid."""

    def _render(self):
        return render_to_string(TEMPLATE, CONTEXT)

    def test_kpi_section_is_no_longer_a_card_grid(self):
        html = self._render()
        self.assertNotIn("summary-box", html, "KPI cards are back in the PDF")
        self.assertNotIn("summary-grid", html, "KPI card grid is back in the PDF")

    def test_kpi_section_uses_the_shared_data_table(self):
        html = self._render()
        self.assertIn("<h2>Key Performance Indicators</h2>", html)
        self.assertIn('<table class="data">', html)
        self.assertIn(">Metric<", html)
        self.assertIn(">Value<", html)

    def test_kpi_table_lists_all_eight_metrics(self):
        html = self._render()
        for label, _value in KPI_ROWS:
            self.assertIn(
                f"<td>{label}</td>",
                html,
                f"KPI row '{label}' missing from the table",
            )

    def test_kpi_table_shows_the_values(self):
        html = self._render()
        for _label, value in KPI_ROWS:
            self.assertIn(
                f'<td class="text-right">{value}</td>',
                html,
                f"KPI value '{value}' missing from the table",
            )

    def test_kpi_table_keeps_values_right_aligned(self):
        html = self._render()
        self.assertIn('<th class="r" style="width: 30%;">Value</th>', html)

    def test_table_header_has_no_blue_background(self):
        """Ang dati-ganang light-blue (`#f1f5f9`, `#f8fafc`) ay tinanggal."""
        html = self._render()
        for color in ("#f1f5f9", "#f8fafc"):
            self.assertNotIn(
                color,
                html,
                f"light-blue background {color} is back on the report",
            )

    def test_meta_table_and_definitions_are_not_boxed(self):
        """Wala nang box/bg sa PERIOD/EVENT TYPE table at sa Notes & Definitions."""
        html = self._render()
        meta_css = html.split(".meta-table {")[1].split("}")[0]
        self.assertNotIn("border", meta_css, "meta table should not be boxed")
        self.assertNotIn("background", meta_css, "meta table should have no fill")
        defs_css = html.split(".definitions {")[1].split("}")[0]
        self.assertNotIn("background", defs_css, "definitions should have no fill")

    def test_title_text_is_small(self):
        """Ang "ANALYTICS REPORT" ay maliit na lang (dating 15px, ngayon 12px)."""
        html = self._render()
        title_css = html.split(".title-block h1 {")[1].split("}")[0]
        self.assertIn("font-size: 12px", title_css)
        self.assertNotIn("15px", title_css, "oversized title is back")

    def test_data_table_uses_compact_spacing(self):
        html = self._render()
        self.assertIn("padding: 2px 10px", html, "data cells should be compact")
        self.assertIn("line-height: 1.3", html, "data cells should be tight")
        self.assertNotIn(
            "padding: 5px 10px",
            html,
            "oversized cell padding is back",
        )

    def test_first_cells_are_flush_with_the_left_edge(self):
        """Walang left-indent sa unang column — pantay lahat sa kaliwa."""
        html = self._render()
        self.assertIn(
            "table.data th:first-child",
            html,
            "header first cell should lose its left padding",
        )
        self.assertIn(
            "table.data td:first-child",
            html,
            "body first cell should lose its left padding",
        )
        self.assertIn(
            ".meta-table td:first-child",
            html,
            "meta first cell should lose its left padding",
        )
        data_rule = html.split("table.data td:first-child {")[1].split("}")[0]
        self.assertIn("padding-left: 0", data_rule)
        meta_rule = html.split(".meta-table td:first-child {")[1].split("}")[0]
        self.assertIn("padding-left: 0", meta_rule)


class AnalyticsPdfExportTests(TestCase):
    """Ang export endpoint ay gumagawa pa rin ng PDF na may KPI table."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="analytics_admin",
            email="analytics_admin@test.com",
            password="pass12345",
            role="admin",
        )
        self.customer = User.objects.create_user(
            username="analytics_cust",
            email="analytics_cust@test.com",
            password="pass12345",
            role="customer",
        )
        self.url = reverse("admin_analytics_export_pdf")

    def test_export_returns_a_pdf(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_exported_pdf_contains_the_kpi_table_not_cards(self):
        if PdfReader is None:  # pragma: no cover
            self.skipTest("pypdf is not installed")
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        text = "".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(response.content)).pages
        )
        self.assertIn("Key Performance Indicators", text)
        self.assertIn("Metric", text)
        for label, _value in KPI_ROWS:
            self.assertIn(label, text, f"KPI row '{label}' missing from the PDF")

    def test_non_admin_cannot_export(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_left_edge_is_flush_across_sections(self):
        """Sa totoong PDF, pareho ang left indent ng headings, meta at table cells."""
        if PdfReader is None:  # pragma: no cover
            self.skipTest("pypdf is not installed")
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        try:
            page_text = PdfReader(io.BytesIO(response.content)).pages[
                0
            ].extract_text(extraction_mode="layout")
        except TypeError:  # pragma: no cover - older pypdf
            self.skipTest("pypdf layout extraction is not available")

        markers = (
            "Key Performance Indicators",
            "Metric",
            "Total Bookings",
            "PERIOD",
        )
        indents = {}
        for line in page_text.splitlines():
            stripped = line.lstrip(" ")
            if not stripped:
                continue
            for marker in markers:
                if stripped.startswith(marker) and marker not in indents:
                    indents[marker] = len(line) - len(stripped)

        for marker in markers:
            self.assertIn(
                marker,
                indents,
                f"'{marker}' not found on page 1 of the exported PDF",
            )
            self.assertLessEqual(
                indents[marker],
                1,
                f"'{marker}' is indented {indents[marker]} columns "
                "from the left edge — content should be flush left",
            )