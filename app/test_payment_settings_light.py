"""Regression tests para sa Payment Settings (/staff/gcash-config/) light mode.

Ang title na "Required Initial Payment" ay may class na .text-heading na
may tanging `.text-heading { color: #fff; }` rule — walang light-mode
override, kaya puti ito sa puting card ng light mode. Ang .text-secondary
(description/label) at .text-muted (hint) ay may sariling light rules na,
kaya sila ay visible; ang .text-heading lang ang nawawala.
"""
from pathlib import Path

from django.test import TestCase

BASE_DIR = Path(__file__).resolve().parent.parent


class PaymentSettingsLightModeTests(TestCase):
    def test_text_heading_has_dark_light_mode_rule(self):
        css = (BASE_DIR / "static" / "css" / "admin_payment.css").read_text(encoding="utf-8")
        selector = '[data-theme="light"] .text-heading {'
        self.assertIn(selector, css, "Nawawala ang light-mode rule ng .text-heading.")
        block = css.split(selector)[1].split("}")[0]
        # Dapat madilim ang kulay (hindi puti) para makita sa puting card
        self.assertNotIn("#fff", block)
        self.assertIn("color: #111827", block)

    def test_dark_mode_rule_still_exists(self):
        # Hindi dapat alisin ang dark-mode default (puti sa madilim na card)
        css = (BASE_DIR / "static" / "css" / "admin_payment.css").read_text(encoding="utf-8")
        self.assertIn(".text-heading { color: #fff; }", css)

    def test_gcash_config_template_uses_text_heading_with_cache_buster(self):
        template = (
            BASE_DIR / "app" / "templates" / "admin" / "payment" / "admin_gcash_config.html"
        ).read_text(encoding="utf-8")
        self.assertIn('class="text-heading"', template)
        self.assertIn("Required Initial Payment", template)
        # Cache buster para hindi mapaglaruan ng browser ang lumang CSS
        self.assertIn("css/admin_payment.css' %}?v=", template)

    def test_sibling_light_rules_still_present(self):
        # Ang description/label (.text-secondary) at hint (.text-muted) ay
        # dapat may light rules pa rin — kung mawala, maitim/puti rin sila.
        payment_css = (BASE_DIR / "static" / "css" / "admin_payment.css").read_text(
            encoding="utf-8"
        )
        light_mode_css = (BASE_DIR / "static" / "css" / "admin_light_mode.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("[data-theme=\"light\"] .text-secondary {", light_mode_css)
        self.assertIn("[data-theme=\"light\"] .text-muted,", payment_css)
