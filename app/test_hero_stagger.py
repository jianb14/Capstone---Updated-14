"""Regression tests para sa staggered hero entrance (About/Service/Package/Gallery).

Bug — sabay-sabay ang fade: sa home hero may staggered delays
(label 0.05s -> title 0.25s -> subtitle 0.45s -> CTA 0.65s), pero sa
about/services/package/gallery walang animation ang mga hero element kaya
sabay-sabay ang lahat (buong .page lang ang nagfa-fade). Dapat isa-isang
nagfa-fade gaya ng home hero.
"""
from pathlib import Path

from django.test import TestCase

BASE_DIR = Path(__file__).resolve().parent.parent


class InnerHeroStaggerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")

    def test_label_fades_first(self):
        block = self.css.split(".about-tagline {")[1].split("}")[0]
        self.assertIn("animation: fadeInUp 0.7s ease-out 0.05s both;", block)

    def test_titles_fade_second(self):
        for sel in (".about-hero h1,", ".packages-hero h1,", ".gallery-hero h1 {"):
            self.assertIn(sel, self.css)
        idx = self.css.find(".about-hero h1,")
        block = self.css[idx:self.css.find("}", idx)]
        self.assertIn("0.25s both", block)

    def test_subtitles_fade_third(self):
        idx = self.css.find(".about-hero > p,")
        self.assertNotEqual(idx, -1)
        block = self.css[idx:self.css.find("}", idx)]
        self.assertIn("0.45s both", block)

    def test_scroll_cue_uses_backwards_fill(self):
        # "both" fill ang sisira sa .is-hidden hide-on-scroll at sa centering,
        # kaya "backwards" lang ang dapat gamitin ng scroll cue.
        idx = self.css.find(".about-hero .scroll-down,")
        self.assertNotEqual(idx, -1)
        block = self.css[idx:self.css.find("}", idx)]
        self.assertIn("fadeIn", block)
        self.assertIn("backwards", block)
        self.assertNotIn("both", block)

    def test_reduced_motion_covers_inner_heroes(self):
        idx = self.css.find("@media (prefers-reduced-motion: reduce)")
        block = self.css[idx:]
        for sel in (
            ".about-tagline",
            ".about-hero h1",
            ".packages-hero h1",
            ".gallery-hero h1",
            ".about-hero .scroll-down",
        ):
            self.assertIn(sel, block)

    def test_pages_render_hero_structure(self):
        for url in ("/about/", "/services/", "/package/", "/gallery/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn("<h1", response.content.decode("utf-8"))

    def test_staticfiles_synced_and_cache_busted(self):
        collected = (BASE_DIR / "staticfiles" / "css" / "base.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".about-hero .scroll-down,", collected)
        base_template = (BASE_DIR / "app" / "templates" / "client" / "base.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("css/base.css' %}?v=20261012i", base_template)
