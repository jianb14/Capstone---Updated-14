"""Regression tests para sa password show/hide eye sa light mode.

Puti (255, 255, 255) ang eye-view.png at eye-hide.png, kaya kapag naka-light
mode ay invisible ang eye sa puting input background. Kailangan ng
[data-theme="light"] filter: brightness(0) rule sa bawat password field na may
eye (auth pages, client profile, admin profile) — kapareho ng ginawa sa puting
logo images (auth.css / base.css / admin_light_mode.css).
"""
from pathlib import Path

from django.test import TestCase

BASE_DIR = Path(__file__).resolve().parent.parent


class PasswordEyeLightModeTests(TestCase):
    def test_auth_pages_pass_icon_turns_black_in_light_mode(self):
        css = (BASE_DIR / "static" / "css" / "auth.css").read_text(encoding="utf-8")
        selector = '[data-theme="light"] .pass-icon {'
        self.assertIn(selector, css, "Nawawala ang light-mode rule ng .pass-icon.")
        block = css.split(selector)[1].split("}")[0]
        self.assertIn("filter: brightness(0);", block)

    def test_client_profile_toggle_icon_turns_black_in_light_mode(self):
        css = (BASE_DIR / "static" / "css" / "my_profile.css").read_text(encoding="utf-8")
        selector = '[data-theme="light"] .password-toggle-icon {'
        self.assertIn(selector, css, "Nawawala ang light-mode rule ng .password-toggle-icon.")
        block = css.split(selector)[1].split("}")[0]
        self.assertIn("filter: brightness(0);", block)

    def test_admin_profile_modal_toggle_turns_black_in_light_mode(self):
        template = (
            BASE_DIR / "app" / "templates" / "admin" / "admin_profile.html"
        ).read_text(encoding="utf-8")
        selector = '[data-theme="light"] .apm-toggle {'
        self.assertIn(selector, template, "Nawawala ang light-mode rule ng .apm-toggle.")
        block = template.split(selector)[1].split("}")[0]
        self.assertIn("filter: brightness(0);", block)

    def test_light_rules_target_the_classes_used_by_templates(self):
        # Dapat mag-match ang class sa templates sa mga light-mode rule sa itaas,
        # kung hindi ay hindi maga-apply ang filter (tahimik na pagkakamali).
        auth_dir = BASE_DIR / "app" / "templates" / "auth"
        for name in ("login.html", "register.html", "reset_password.html"):
            source = (auth_dir / name).read_text(encoding="utf-8")
            self.assertIn('class="pass-icon"', source, f"{name}: walang pass-icon.")
        client = (BASE_DIR / "app" / "templates" / "client" / "my_profile.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('class="password-toggle-icon"', client)
        admin = (BASE_DIR / "app" / "templates" / "admin" / "admin_profile.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('class="apm-toggle"', admin)

    def test_eye_icons_stay_white(self):
        # Naka-document ang root cause: puti ang eye PNGs kaya nababasa lang
        # sila sa dark mode. Kapag pinalitan ng maitim na PNG ito, masisira naman
        # ang dark mode — dapat parehong i-review ang filter rules at ang asset.
        from PIL import Image

        for name in ("eye-view.png", "eye-hide.png"):
            img = Image.open(BASE_DIR / "static" / "images" / name).convert("RGBA")
            colors = img.getcolors(maxcolors=4096) or []
            opaque = [rgba for _, rgba in colors if rgba[3] > 128]
            self.assertTrue(opaque, f"{name}: walang visible pixel.")
            for rgba in opaque:
                self.assertGreaterEqual(
                    min(rgba[:3]),
                    250,
                    f"{name}: hindi na puro puti ang visible pixels — baka "
                    "napalitan ang asset; i-review ang brightness(0) rules.",
                )
