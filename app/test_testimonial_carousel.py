"""Regression tests para sa testimonial carousel (Home/About) fade + swipe.

Bug 1 — paulit-ulit na fade-in: dati ay bawat `.tcarousel-card` ang nasa
scroll-reveal selector, kaya kada swipe ay nagfa-fade in din ang bagong
card. Dapat ang buong `.testimonial-carousel` container lang ang
nagfa-fade in nang isang beses.

Bug 2 — walang swipe cursor: dati ay walang grab/grabbing cursor ang
`.carousel-viewport`, kaya hindi halatang nadda-drag ang reviews.
"""
from pathlib import Path

from django.test import TestCase

BASE_DIR = Path(__file__).resolve().parent.parent


class TestimonialCarouselTests(TestCase):
    def test_reveal_targets_carousel_container_not_cards(self):
        js = (BASE_DIR / "static" / "js" / "theme-toggle.js").read_text(encoding="utf-8")
        self.assertIn("'.testimonial-carousel',", js)
        self.assertNotIn(".carousel-track .tcarousel-card", js)

    def test_viewport_has_swipe_cursor(self):
        css = (BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")
        viewport_block = css.split(".carousel-viewport {")[1].split("}")[0]
        self.assertIn("cursor: grab;", viewport_block)
        self.assertIn(".carousel-viewport:active", css)
        active_block = css.split(".carousel-viewport:active")[1].split("}")[0]
        self.assertIn("cursor: grabbing;", active_block)

    def test_manual_swipe_still_supported(self):
        # Hindi dapat alisin ang pointer-drag handlers — doon nakasandal
        # ang manual swipe (hindi lang auto-swipe + dots).
        template = (BASE_DIR / "app" / "templates" / "client" / "base.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('addEventListener("pointerdown"', template)
        self.assertIn('addEventListener("pointerup"', template)

    def test_staticfiles_synced_and_cache_busted(self):
        # Kapag nagbago ang static files, dapat naka-sync ang staticfiles/
        # copy at may cache buster para hindi maluma ang browser.
        static_css = (BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")
        collected_css = (BASE_DIR / "staticfiles" / "css" / "base.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("cursor: grab;", collected_css)
        self.assertEqual(
            "cursor: grab;" in static_css, "cursor: grab;" in collected_css
        )
        static_js = (BASE_DIR / "static" / "js" / "theme-toggle.js").read_text(
            encoding="utf-8"
        )
        collected_js = (BASE_DIR / "staticfiles" / "js" / "theme-toggle.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("'.testimonial-carousel',", collected_js)
        self.assertEqual(
            "'.testimonial-carousel'," in static_js,
            "'.testimonial-carousel'," in collected_js,
        )
        base_template = (BASE_DIR / "app" / "templates" / "client" / "base.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("css/base.css' %}?v=", base_template)
        self.assertIn("js/theme-toggle.js' %}?v=", base_template)
