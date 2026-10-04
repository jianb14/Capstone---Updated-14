"""Tests for the customer payment receipt PDF.

Regression guard for the missing receipt logo: reportlab's ``drawImage``
anchors on the image centre and falls back to the image's pixel height when
``height`` is omitted, which used to push the logo completely above the A4
page. The tests below assert the logo is embedded *and* positioned inside the
page bounds (top-left of the header), plus the header layout: title and
subtitle stacked left-aligned under the logo, a small title size, and a
light-gray divider line.
"""
import io
import unittest
from datetime import date, time
from decimal import Decimal

from django.contrib.staticfiles import finders
from django.test import RequestFactory, TestCase

from .models import Booking, Payment, User
from .views.payments import download_payment_receipt_pdf

try:  # pypdf is pulled in by xhtml2pdf (see requirements.txt)
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - optional at runtime
    PdfReader = None

# reportlab's A4 page (points).
PAGE_WIDTH = 595.2756
PAGE_HEIGHT = 841.8898

LOGO_STATIC_PATH = "images/BalloorinaBlack.png"


def _page_content(pdf_bytes):
    """Concatenated, filter-decoded content streams of every page."""
    chunks = []
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        chunks.append(page.get_contents().get_data().decode("latin-1", errors="replace"))
    return "\n".join(chunks)


def _image_matrices(pdf_bytes):
    """``[(x, y, width, height), ...]`` for each image drawn on the page.

    Parses the ``a 0 0 d e f cm /Name Do`` group reportlab emits for images.
    """
    tokens = _page_content(pdf_bytes).split()
    matrices = []
    for index, token in enumerate(tokens):
        if token != "Do" or index == 0:
            continue
        if not tokens[index - 1].startswith("/"):
            continue
        # Walk back to the operator's operands ("a 0 0 d e f cm").
        for back in range(index - 1, max(index - 10, 0), -1):
            if tokens[back] == "cm" and back >= 6:
                try:
                    a, _b, _c, d, e, f = (float(v) for v in tokens[back - 6:back])
                except ValueError:
                    break
                matrices.append((e, f, a, d))
                break
    return matrices


def _font_size_for(pdf_bytes, first_token, second_token):
    """Font size (pt) of the text run drawn as ``first_token second_token...``.

    reportlab puts the font selection (``/Fx size Tf``) in a BT..ET block
    *before* the block that shows the text, so walk backwards across block
    boundaries to the nearest ``Tf`` -- that is the active font.
    """
    tokens = _page_content(pdf_bytes).split()
    for index in range(len(tokens) - 1):
        if tokens[index] != first_token:
            continue
        if not tokens[index + 1].startswith(second_token):
            continue
        for back in range(index - 1, max(index - 20, 0), -1):
            if tokens[back] == "Tf":
                try:
                    return float(tokens[back - 1])
                except ValueError:
                    return None
        return None
    return None


def _stroke_colors(pdf_bytes):
    """``[(r, g, b), ...]`` for each RGB stroke-color (``RG``) operator."""
    tokens = _page_content(pdf_bytes).split()
    colors = []
    for index, token in enumerate(tokens):
        if token != "RG" or index < 3:
            continue
        try:
            colors.append(tuple(float(v) for v in tokens[index - 3:index]))
        except ValueError:
            continue
    return colors


def _text_origin(pdf_bytes, first_token, second_token=None):
    """``(x, y)`` origin from the ``Tm`` operator that positions a text run.

    reportlab emits ``1 0 0 1 x y Tm`` right before the text-showing operator,
    so walk backwards from the run to the nearest ``Tm``.
    """
    tokens = _page_content(pdf_bytes).split()
    for index in range(len(tokens) - 1):
        if tokens[index] != first_token:
            continue
        if second_token is not None and not tokens[index + 1].startswith(second_token):
            continue
        for back in range(index - 1, max(index - 8, 0), -1):
            if tokens[back] == "Tm" and back >= 6:
                try:
                    values = [float(v) for v in tokens[back - 6:back]]
                except ValueError:
                    return None
                return values[4], values[5]
    return None


@unittest.skipUnless(PdfReader, "pypdf is not installed")
class ReceiptLogoPlacementTests(TestCase):
    """The receipt must carry a logo that actually lands on the page."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="cust", email="cust@test.com", password="pass12345", role="customer"
        )
        self.booking = Booking.objects.create(
            user=self.user,
            event_date=date(2099, 6, 15),
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Test Venue",
            package_type="Package A",
            total_price=Decimal("5799.00"),
            status="confirmed",
        )
        self.payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal("5799.00"),
            payment_method="gcash",
            payment_type="full",
            payment_status="verified",
            transaction_ref="TEST-RECEIPT-REF-1",
        )

    def _get_pdf(self):
        request = RequestFactory().get(
            f"/my-payments/{self.payment.id}/receipt-pdf/"
        )
        request.user = self.user
        response = download_payment_receipt_pdf(request, self.payment.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        return response.content

    def test_logo_asset_is_available_to_the_finder(self):
        self.assertIsNotNone(finders.find(LOGO_STATIC_PATH))

    def test_receipt_embeds_exactly_one_image(self):
        matrices = _image_matrices(self._get_pdf())
        self.assertTrue(matrices, "receipt draws no image -- the logo is missing")
        self.assertEqual(len(matrices), 1)

    def test_logo_is_drawn_inside_the_page_bounds(self):
        data = self._get_pdf()
        x, y, logo_w, logo_h = _image_matrices(data)[0]

        self.assertGreater(logo_w, 0)
        self.assertGreater(logo_h, 0)
        # Regression: the logo used to sit at y=~869.6 on an 841.9pt page.
        self.assertGreaterEqual(y, 0, "logo is drawn below the page")
        self.assertLessEqual(
            y + logo_h,
            PAGE_HEIGHT,
            "logo is drawn above the top of the page (invisible)",
        )
        self.assertGreaterEqual(x, 0, "logo is drawn left of the page")
        self.assertLessEqual(x + logo_w, PAGE_WIDTH, "logo overflows the right edge")

    def test_logo_keeps_its_aspect_ratio(self):
        _, _, logo_w, logo_h = _image_matrices(self._get_pdf())[0]
        # Source logo is 956x261 -> aspect ratio ~3.66:1.
        self.assertAlmostEqual(logo_w / logo_h, 956 / 261, places=1)

    def test_logo_is_at_the_top_left(self):
        x, y, _, logo_h = _image_matrices(self._get_pdf())[0]
        self.assertLess(
            x, PAGE_WIDTH / 2, "logo should be placed on the left side of the header"
        )
        self.assertGreater(
            y + logo_h,
            PAGE_HEIGHT - 60,
            "logo should be placed at the top of the page",
        )

    def test_title_text_is_small(self):
        size = _font_size_for(self._get_pdf(), "(Payment", "Receipt)")
        self.assertIsNotNone(size, "Payment Receipt title not found in the PDF")
        self.assertLessEqual(size, 16, "Payment Receipt title should be 16pt or smaller")

    def test_title_stack_is_on_the_left_under_the_logo(self):
        data = self._get_pdf()
        title = _text_origin(data, "(Payment", "Receipt)")
        subtitle = _text_origin(data, "(Balloorina.ph")
        logo_x, logo_y, _, _ = _image_matrices(data)[0]

        self.assertIsNotNone(title, "Payment Receipt title position not found")
        self.assertIsNotNone(subtitle, "subtitle position not found")
        # Everything is stacked on the left, flush with the logo...
        self.assertAlmostEqual(title[0], logo_x, places=1)
        self.assertAlmostEqual(subtitle[0], logo_x, places=1)
        # ...in order: logo on top, then the title, then the subtitle.
        self.assertLess(title[1], logo_y, "title should sit below the logo")
        self.assertLess(subtitle[1], title[1], "subtitle should sit below the title")

    def test_divider_line_is_light_gray(self):
        colors = _stroke_colors(self._get_pdf())
        self.assertTrue(colors, "no stroke colors found in the receipt")
        self.assertTrue(
            any(min(color) >= 0.8 for color in colors),
            f"divider line is not light gray (strokes found: {colors})",
        )
        self.assertFalse(
            any(all(abs(v - 0.4) < 1e-6 for v in color) for color in colors),
            "divider line still uses the old dark gray (0.4)",
        )

    def test_receipt_body_content_still_rendered(self):
        content = _page_content(self._get_pdf())
        self.assertIn("Payment Receipt", content)
        self.assertIn("Official Billing Statement", content)


class ReceiptPdfAccessControlTests(TestCase):
    """Only the owner (or admin/staff) may download a receipt."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", email="owner@test.com", password="pass12345", role="customer"
        )
        self.other = User.objects.create_user(
            username="other", email="other@test.com", password="pass12345", role="customer"
        )
        self.booking = Booking.objects.create(
            user=self.owner,
            event_date=date(2099, 6, 15),
            event_time=time(10, 0),
            event_type="Birthday",
            event_location="Test Venue",
            total_price=Decimal("5799.00"),
            status="confirmed",
        )
        self.payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal("5799.00"),
            payment_method="gcash",
            payment_type="full",
            payment_status="verified",
            transaction_ref="TEST-RECEIPT-REF-2",
        )

    def test_other_customer_is_forbidden(self):
        request = RequestFactory().get("/")
        request.user = self.other
        response = download_payment_receipt_pdf(request, self.payment.id)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_download(self):
        request = RequestFactory().get("/")
        request.user = self.owner
        response = download_payment_receipt_pdf(request, self.payment.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("receipt_PAY", response["Content-Disposition"])
