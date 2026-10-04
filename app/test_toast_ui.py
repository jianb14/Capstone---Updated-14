"""Regression tests para sa client-side toast (SweetAlert2) design at pag-iisa.

Dalawang bug ang hinahawakan ng file na ito:

1. DOUBLE TOAST / "doble" na itsura.
   Sa SweetAlert2 v11, ang element ng TOAST ay may klaseng
   `swal2-popup swal2-toast`. Kaya ang dialog-only na rule na
   `.swal2-popup { }` ay NATATAMA rin ang toast — kaya naipapaloob
   pa ang default border ng toast, naaabot sa dating "dalawang
   border" at malaking border-radius. Ang mga dialog rule ay dapat
   `.swal2-popup:not(.swal2-toast)` para hindi mahit ang toast.

2. NAWALANG SEMANTIC NA KULAY ng delete.
   Ang dating `.swal2-popup .swal2-confirm { background-color: #0d6efd
   !important }` ay nanalo laban sa inline `confirmButtonColor`
   dahil sa `!important` — kaya nagiging BLUE ang "Yes, delete it!"
   kahit RED ang hinihingi. Walang dapat na color override sa buttons;
   ang kulay ay dapat galing sa per-call na confirmButtonColor /
   cancelButtonColor (parareho sa admin_base.html).

Kasama rin:
   - Iisang pinagmumulan ng toast (`AppToast`) na may dedupe guard,
     para hindi ma-stack ang dalawang toast sa iisang screen.
   - Hindi na dapat mag-load ang SweetAlert2 CDN nang paulit-ulit
     sa loob ng isang page.
   - Responsive tiers (tablet <=1024px, mobile <=768px, <=480px) na may
     `calc()` guard para hindi lumabas ang toast sa viewport.
"""
import re
from pathlib import Path

from django.test import Client, TestCase

from .models import User

BASE_DIR = Path(__file__).resolve().parent.parent
CLIENT_TEMPLATES = BASE_DIR / "app" / "templates" / "client"
STATIC_JS = BASE_DIR / "static" / "js"

REVIEWS_PAGES = ["my_reviews.html", "reviews.html"]


class ToastCssScopeTests(TestCase):
    """CSS sa base.html: dapat saklawin ang toast at dialog nang hiwalay."""

    def setUp(self):
        self.base_css = (CLIENT_TEMPLATES / "base.html").read_text(encoding="utf-8")

    def _css_block(self):
        """Isinasa lang ang <style> na may swal2 rules (walang comment)."""
        start = self.base_css.find(".swal2-container")
        self.assertNotEqual(start, -1, "Wala nang .swal2-container sa base.html.")
        end = self.base_css.find("</style>", start)
        css = self.base_css[start:end]
        # Alisin ang CSS comment — kung hindi, mahihit ng explanatory
        # comment ang selector (hal. `.swal2-popup { }`) sa scan.
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def test_dialog_rules_are_scoped_away_from_toasts(self):
        """Bawat selector na may `.swal2-popup` ay dapat may `:not(.swal2-toast)`.

        Sa SweetAlert2 v11, ang toast ay `.swal2-popup.swal2-toast`, kaya
        ang unscoped na `.swal2-popup` ay makakatama rin sa toast.
        """
        css = self._css_block()
        unscoped = []
        for selector in re.findall(r"([^{}]+)\{[^{}]*\}", css):
            for part in selector.split(","):
                part = part.strip()
                if ".swal2-popup" in part and ":not(.swal2-toast)" not in part:
                    unscoped.append(part)
        self.assertEqual(
            sorted(set(unscoped)),
            [],
            "May .swal2-popup selector na hindi naka-scope sa :not(.swal2-toast) "
            "— mahahit din ito sa toast at magdodoble ang border: "
            + ", ".join(sorted(set(unscoped))),
        )

    def test_toast_and_dialog_rules_both_exist(self):
        css = self._css_block()
        self.assertIn(".swal2-toast {", css)
        self.assertIn(".swal2-popup:not(.swal2-toast) {", css)

    def test_buttons_have_no_color_override(self):
        """Ang delete button ay dapat manatiling RED (confirmButtonColor)."""
        css = self._css_block()
        for prop in ("background-color", "border-color", "border"):
            pattern = (
                r"\.swal2-popup:not\(\.swal2-toast\)\s+\.swal2-(confirm|cancel)[^{]*\{"
                r"[^}]*\b" + prop + r"\s*:"
            )
            self.assertIsNone(
                re.search(pattern, css),
                f"May `{prop}` override sa swal2 confirm/cancel — "
                "masisira nito ang per-call na confirmButtonColor.",
            )

    def test_confirm_button_keeps_only_shape_properties(self):
        css = self._css_block()
        match = re.search(
            r"\.swal2-popup:not\(\.swal2-toast\)\s+\.swal2-confirm\s*\{([^}]*)\}", css
        )
        self.assertIsNotNone(match, "Wala nang .swal2-confirm rule.")
        allowed = {"border-radius", "font-weight", "padding", "font-size"}
        props = {
            d.split(":")[0].strip()
            for d in (part.strip() for part in match.group(1).split(";"))
            if d and not d.startswith("/*")
        }
        self.assertTrue(
            props.issubset(allowed),
            f"May labas na property sa .swal2-confirm: {sorted(props - allowed)}",
        )

    def test_toast_responsive_tiers_exist(self):
        css = self._css_block()
        for breakpoint in ("1024px", "768px", "480px"):
            self.assertIn(
                f"@media (max-width: {breakpoint})",
                css,
                f"Wala ang responsive tier na {breakpoint}.",
            )

    def test_toast_has_viewport_width_guard(self):
        """Dapat may calc(100vw - ...) para hindi lumabas ang toast sa screen."""
        css = self._css_block()
        toast_max_widths = re.findall(
            r"\.swal2-toast\s*\{[^}]*max-width\s*:([^;]+);", css
        )
        self.assertTrue(
            toast_max_widths,
            "Walang max-width ang .swal2-toast — puwede itong lumabas sa viewport.",
        )
        for value in toast_max_widths:
            self.assertIn(
                "100vw", value, f"Ang max-width ng toast ({value}) ay walang 100vw guard."
            )


class SharedToastHelperTests(TestCase):
    """Iisang pinagmumulan ng toast + dedupe guard."""

    def setUp(self):
        self.helper_path = STATIC_JS / "toast_helper.js"
        self.helper = self.helper_path.read_text(encoding="utf-8")
        self.base_html = (CLIENT_TEMPLATES / "base.html").read_text(encoding="utf-8")

    def test_helper_file_exists(self):
        self.assertTrue(
            self.helper_path.exists(), "Wala pa ang static/js/toast_helper.js."
        )

    def test_helper_is_loaded_by_client_base(self):
        self.assertIn("js/toast_helper.js", self.base_html)

    def test_helper_loads_after_sweetalert2_cdn(self):
        """Kailangan ng CDN bago tumakbo ang helper (Swal.mixin)."""
        cdn = self.base_html.find("sweetalert2@11")
        helper = self.base_html.find("js/toast_helper.js")
        self.assertNotEqual(cdn, -1, "Wala nang SweetAlert2 CDN sa base.html.")
        self.assertLess(cdn, helper, "Mas maaga ang helper kaysa sa SweetAlert2 CDN.")

    def test_helper_exposes_apptoast_with_dedupe_guard(self):
        self.assertIn("global.AppToast", self.helper)
        self.assertIn("withDedupe", self.helper)
        self.assertIn("DEDUPE_WINDOW_MS", self.helper)

    def test_client_pages_no_longer_define_own_swal_mixin(self):
        """Ang mga client page ay dapat gumamit ng AppToast, hindi sariling mixin."""
        for name in REVIEWS_PAGES + ["my_profile.html", "report_concern.html"]:
            source = (CLIENT_TEMPLATES / name).read_text(encoding="utf-8")
            self.assertNotIn(
                "Swal.mixin(",
                source,
                f"Si {name} ay may sariling Swal.mixin() — dapat AppToast ang gamitin.",
            )

    def test_global_messages_handler_uses_shared_toast(self):
        self.assertIn("AppToast.fire(", self.base_html)

    def test_sweetalert2_cdn_loaded_only_once_per_page(self):
        """Hindi dapat mag-load ang CDN nang paulit-ulit sa isang page."""
        for name in REVIEWS_PAGES + ["my_profile.html"]:
            source = (CLIENT_TEMPLATES / name).read_text(encoding="utf-8")
            self.assertNotIn(
                "sweetalert2@11",
                source,
                f"Si {name} ay nag-lo-load muli ng SweetAlert2 CDN "
                "(naka-load na ito sa client/base.html).",
            )


class DeleteReviewToastTests(TestCase):
    """Ang delete/edit flow: isang toast bawat action, at RED ang delete."""

    def _page(self, name):
        return (CLIENT_TEMPLATES / name).read_text(encoding="utf-8")

    def test_delete_confirm_button_is_red(self):
        for name in REVIEWS_PAGES:
            self.assertIn(
                "confirmButtonColor: '#dc2626'",
                self._page(name),
                f"Si {name} ay dapat may RED na confirm button para sa delete.",
            )

    def test_delete_error_branch_never_throws_on_html_body(self):
        """Ang `await response.json()` sa error branch ay nag-ta-throw sa HTML
        404/500, kaya lumulabas sa catch — maling toast lang ang dating na
        bunga. dapat may .catch() para hindi mag-double-fire."""
        for name in REVIEWS_PAGES:
            source = self._page(name)
            self.assertNotIn(
                "const data = await response.json();",
                source,
                f"Si {name}: ang error branch ay nagta-throw sa HTML body. "
                "Gumamit ng .json().catch(() => ({}))",
            )
            self.assertIn(
                "await response.json().catch(() => ({}))",
                source,
                f"Si {name} ay walang safe na .json().catch().",
            )

    def test_delete_and_update_error_toasts_are_distinct_messages(self):
        for name in REVIEWS_PAGES:
            source = self._page(name)
            self.assertIn("Delete failed", source, f"Si {name}.")
            self.assertIn("Update failed", source, f"Si {name}.")
            self.assertIn("An error occurred while deleting.", source, f"Si {name}.")
            self.assertIn("An error occurred while updating.", source, f"Si {name}.")


class DeleteReviewViewTests(TestCase):
    """Sanity check sa server side ng delete_review (error body = JSON)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="toast_tester", password="pw", email="t@example.com"
        )
        self.other = User.objects.create_user(
            username="toast_other", password="pw", email="o@example.com"
        )
        self.client.force_login(self.user)

    def _create_review(self, user=None):
        from .models import Booking, Review

        booking, _ = Booking.objects.get_or_create(
            user=user or self.user,
            event_date="2030-01-01",
            defaults={
                "event_location": "Test Venue",
                "total_price": "1000.00",
                "status": "completed",
            },
        )
        return Review.objects.create(
            user=user or self.user,
            booking=booking,
            rating=5,
            comment="Test review para sa toast",
        )

    def test_delete_review_returns_json_success(self):
        review = self._create_review()
        response = self.client.post(f"/reviews/{review.id}/delete/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())

    def test_delete_other_users_review_is_not_found(self):
        review = self._create_review(user=self.other)
        response = self.client.post(f"/reviews/{review.id}/delete/")
        self.assertEqual(response.status_code, 404)


class RenderedToastOutputTests(TestCase):
    """I-render ang aktuwal na HTML para makita ang katotohanan.

    Mas malakas ito kaysa sa pagbabasa ng template file, dahil
    nakikita nito ang tunay na na-render na `<script>` at `<style>`.
    """

    def setUp(self):
        # Ang /my-reviews/ ay nangangailangan ng role="customer".
        self.user = User.objects.create_user(
            username="toast_render", password="pw", email="r@example.com"
        )
        self.user.role = "customer"
        self.user.save(update_fields=["role"])
        self.client.force_login(self.user)

    def _render(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, f"Hindi na-load ang {path}")
        return response.content.decode("utf-8")

    def test_reviews_page_renders_helper_and_no_page_mixin(self):
        html = self._render("/reviews/")
        self.assertIn("js/toast_helper.js", html)
        self.assertIn("AppToast.mixin(", html)
        self.assertNotIn("Swal.mixin(", html)
        # Isang SweetAlert2 CDN load lang bawat page.
        self.assertEqual(html.count("sweetalert2@11"), 1)

    def test_my_reviews_page_renders_helper_and_no_page_mixin(self):
        html = self._render("/my-reviews/")
        self.assertIn("js/toast_helper.js", html)
        self.assertIn("AppToast.mixin(", html)
        self.assertNotIn("Swal.mixin(", html)
        self.assertEqual(html.count("sweetalert2@11"), 1)

    def test_services_page_loads_helper_once(self):
        html = self._render("/services/")
        self.assertIn("js/toast_helper.js", html)
        self.assertEqual(html.count("sweetalert2@11"), 1)

    def test_rendered_html_has_no_unscoped_popup_selector(self):
        """Walang dialog rule na makakahit sa toast sa rendered HTML."""
        for path in ("/reviews/", "/my-reviews/", "/services/"):
            html = self._render(path)
            # Alisin muna ang HTML/CSS comment bago mag-scan.
            stripped = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
            stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
            for selector in re.findall(r"([^{}]+)\{[^{}]*\}", stripped):
                for part in selector.split(","):
                    part = part.strip()
                    if ".swal2-popup" in part and ":not(.swal2-toast)" not in part:
                        self.fail(
                            f"{path}: may unscoped selector na makakahit sa "
                            f"toast -> {part!r}"
                        )

    def test_rendered_delete_button_is_red(self):
        for path in ("/reviews/", "/my-reviews/"):
            html = self._render(path)
            self.assertIn(
                "confirmButtonColor: '#dc2626'",
                html,
                f"Si {path} ay dapat RED ang delete confirm button.",
            )