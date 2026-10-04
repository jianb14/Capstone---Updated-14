"""Regression tests para sa client-side mobile navbar layout.

Ang dating bug: may zero-width space (&#8203;) sa loob ng logo anchor. Dahil
inline ang anchor, gumagawa ito ng phantom line box (mula sa inherited
line-height: 1.6), kaya lumulutang pataas ang logo at hindi pantay sa 40px
hamburger at sa Login button sa mobile. Kasama na rin dito ang pag-check na
isang source of truth (--nav-h) na lang ang navbar height na ginagamit ng
mobile drawer at overlay.
"""
from pathlib import Path

from django.test import Client, TestCase

from .models import User

BASE_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "base.css"


class NavbarMobileLayoutTests(TestCase):
    def setUp(self):
        self.client = Client()

    # ---- Zero-width space sa logo anchor (ang ugat ng misalignment) ----

    def test_guest_navbar_logo_anchor_has_no_zero_width_space(self):
        body = self.client.get("/").content.decode("utf-8")
        start = body.find('class="nav-logo"')
        self.assertNotEqual(start, -1, "Hindi na-render ang .nav-logo anchor.")
        anchor = body[start:body.find("</a>", start)]
        self.assertNotIn("\u200b", anchor)
        self.assertNotIn("&#8203;", anchor)
        # Ang logo image mismo ay dapat nasa loob ng flex anchor.
        self.assertIn('class="logo"', anchor)

    def test_customer_navbar_logo_anchor_has_no_zero_width_space(self):
        User.objects.create_user(
            username="navcust",
            email="navcust@test.com",
            password="pass12345",
            role="customer",
        )
        self.client.force_login(User.objects.get(username="navcust"))
        body = self.client.get("/").content.decode("utf-8")
        start = body.find('class="nav-logo"')
        self.assertNotEqual(start, -1, "Hindi na-render ang .nav-logo anchor.")
        anchor = body[start:body.find("</a>", start)]
        self.assertNotIn("\u200b", anchor)
        self.assertIn('class="logo"', anchor)

    def test_home_page_has_no_stray_zero_width_space(self):
        body = self.client.get("/").content.decode("utf-8")
        self.assertNotIn("\u200b", body)

    # ---- Accessible hamburger ----

    def test_hamburger_is_an_accessible_button(self):
        body = self.client.get("/").content.decode("utf-8")
        self.assertIn('type="button" class="mobile-menu"', body)
        self.assertIn('aria-label="Open menu"', body)
        self.assertIn('aria-expanded="false"', body)

    # ---- CSS: ang aktwal na centering at ang --nav-h source of truth ----

    def test_logo_anchor_rule_makes_the_image_the_flex_item(self):
        css = BASE_CSS.read_text(encoding="utf-8")
        idx = css.find(".nav-logo {")
        self.assertNotEqual(idx, -1, "Nawawala ang .nav-logo rule sa base.css.")
        block = css[idx:css.find("}", idx)]
        self.assertIn("display: flex;", block)
        self.assertIn("align-items: center;", block)

    def test_mobile_logo_block_has_no_ineffective_align_self(self):
        # align-self ay hindi umeepekto sa .logo — ang flex item ay ang
        # <a class="nav-logo">, hindi ang <img class="logo">. Sinusuri dito ang
        # actwal na declaration sa loob ng .logo { } (hindi ang comment text).
        css = BASE_CSS.read_text(encoding="utf-8")
        idx = css.find("/* Mobile logo:")
        self.assertNotEqual(idx, -1, "Nawawala ang mobile logo comment/rule.")
        rule_start = css.find(".logo {", idx)
        self.assertNotEqual(rule_start, -1, "Nawawala ang mobile .logo rule.")
        body = css[rule_start:css.find("}", rule_start)]
        self.assertIn("height: 36px;", body)
        self.assertNotIn("align-self:", body)
        self.assertNotIn("align-self :", body)

    def test_desktop_logo_height_is_slightly_reduced(self):
        # Desktop logo: 46px -> 40px. Mas maliit ng onti, pero mas malaki pa
        # sa 36px ng mobile (hindi dapat equal o mas maliit).
        css = BASE_CSS.read_text(encoding="utf-8")
        idx = css.find(".logo {")
        self.assertNotEqual(idx, -1, "Nawawala ang .logo rule sa base.css.")
        block = css[idx:css.find("}", idx)]
        self.assertIn("height: 40px;", block)
        self.assertNotIn("46px", block)
        self.assertIn("width: auto;", block)

    def test_drawer_offset_uses_nav_h_variable(self):
        css = BASE_CSS.read_text(encoding="utf-8")
        self.assertIn("--nav-h: 61px;", css)
        self.assertIn("top: var(--nav-h);", css)
        self.assertIn("calc(100dvh - var(--nav-h))", css)

    def test_no_hardcoded_53px_drawer_offset_left(self):
        css = BASE_CSS.read_text(encoding="utf-8")
        self.assertNotIn("top: 53px;", css)
        self.assertNotIn("100dvh - 53px", css)