"""Regression tests para sa Select Design soft-confirm flow.

Dapat ay hindi na diretso sa design canvas ang "Select Design" button —
bubuksan muna nito ang inclusions modal ng package, kung saan may reminder
note at Back / Continue to Design actions.
Sakop ang dalawang entry point: My Designs modal at Select Design page.
"""
from pathlib import Path

from django.test import TestCase

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIRM_NOTE_SNIPPET = "will be your design's starting point"
CONTINUE_LABEL = "Continue to Design"
# Ang Back button ay pinaikli ("Back" lang) at gumagamit ng FA arrow icon.
BACK_ICON_SNIPPET = 'class="fas fa-arrow-left"'


class SelectDesignConfirmTests(TestCase):
    def test_my_designs_select_button_opens_inclusions_first(self):
        template = (
            BASE_DIR / "app" / "templates" / "client" / "my_designs.html"
        ).read_text(encoding="utf-8")
        # Ang Select Design ay button na nagbubukas ng inclusions modal,
        # hindi direktang link papuntang canvas.
        self.assertIn(
            "onclick=\"openModal('featureModal{{ package.id }}');"
            " closeModal('selectPackageModal');\" class=\"pkg-modal-btn\"",
            template,
        )
        select_block = template.split('class="pkg-modal-btn"')[0].rsplit(
            "<button", 1
        )[1]
        self.assertNotIn("design_canvas", select_block)

    def test_my_designs_inclusions_modal_has_confirm_step(self):
        template = (
            BASE_DIR / "app" / "templates" / "client" / "my_designs.html"
        ).read_text(encoding="utf-8")
        self.assertIn("feature-confirm-note", template)
        self.assertIn(CONFIRM_NOTE_SNIPPET, template)
        self.assertIn(CONTINUE_LABEL, template)
        # Walang arrow sa Continue; arrow icon ay nasa Back lang.
        self.assertNotIn("Continue to Design Canvas", template)
        self.assertNotIn("Back to Packages", template)
        self.assertIn(BACK_ICON_SNIPPET, template)
        self.assertIn("> Back</button>", template)
        # Tanging ang Continue action lang ang papunta sa canvas.
        self.assertIn(
            "{% url 'design_canvas' %}?package_id={{ package.id }}&fresh=1\""
            ' class="feature-modal-btn"',
            template,
        )

    def test_select_page_select_button_opens_inclusions_first(self):
        template = (
            BASE_DIR
            / "app"
            / "templates"
            / "client"
            / "select_design_type.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "onclick=\"openModal('featureModal{{ package.id }}')\"",
            template,
        )
        # Walang direktang design_canvas link sa Select Design button mismo.
        select_idx = template.find("Select Design")
        button_start = template.rfind("<button", 0, select_idx)
        button_block = template[button_start:select_idx]
        self.assertNotIn("design_canvas", button_block)

    def test_select_page_inclusions_modal_has_confirm_step(self):
        template = (
            BASE_DIR
            / "app"
            / "templates"
            / "client"
            / "select_design_type.html"
        ).read_text(encoding="utf-8")
        self.assertIn(CONFIRM_NOTE_SNIPPET, template)
        self.assertIn(CONTINUE_LABEL, template)
        self.assertNotIn("Continue to Design Canvas", template)
        self.assertNotIn("Back to Packages", template)
        self.assertIn(BACK_ICON_SNIPPET, template)

    def test_confirm_styles_synced_in_staticfiles(self):
        static_css = (
            BASE_DIR / "static" / "css" / "my_designs.css"
        ).read_text(encoding="utf-8")
        collected_css = (
            BASE_DIR / "staticfiles" / "css" / "my_designs.css"
        ).read_text(encoding="utf-8")
        for snippet in (
            ".feature-confirm-note {",
            ".feature-modal-actions {",
            ".feature-modal-back {",
        ):
            self.assertIn(snippet, static_css)
            self.assertIn(snippet, collected_css)

    def test_primary_buttons_hover_slightly_gray_in_light_mode(self):
        # Regression: dating #000000 ang hover ng mga black (#111111)
        # primary buttons sa light mode — invisible kaya walang nararamdaman
        # sa hover. Dapat bahagyang mas maputlang gray (#333333) na ngayon:
        # may makitang change pero hindi washed-out gaya ng dating
        # #3f3f46/#6b7280 (mukhang disabled).
        static_css = (
            BASE_DIR / "static" / "css" / "my_designs.css"
        ).read_text(encoding="utf-8")
        collected_css = (
            BASE_DIR / "staticfiles" / "css" / "my_designs.css"
        ).read_text(encoding="utf-8")
        for selector in (
            '[data-theme="light"] .overlay-btn.book-btn:hover',
            '[data-theme="light"] .pkg-modal-btn:hover',
            '[data-theme="light"] .feature-modal-btn:hover',
            '[data-theme="light"] .create-new-btn:hover',
            # Save Name + empty-state create: base hover ay var(--dark-gray)
            # (#6b7280 sa light) — dapat na-overridden ng bahagyang gray.
            '[data-theme="light"] .btn-save:hover',
            '[data-theme="light"] .empty-create-btn:hover',
        ):
            for css in (static_css, collected_css):
                block = css.split(selector)[1].split("}")[0]
                self.assertIn("background: #333333;", block)
                self.assertNotIn("#000000", block)
                self.assertNotIn("#3f3f46", block)
                self.assertNotIn("#6b7280", block)

    def test_back_and_continue_buttons_same_height(self):
        # Dapat pantay ang height ng Back at Continue sa inclusions modal:
        # stretch ang row at flex-centered ang content ng parehong button.
        static_css = (
            BASE_DIR / "static" / "css" / "my_designs.css"
        ).read_text(encoding="utf-8")
        actions_block = static_css.split(".feature-modal-actions {")[1].split(
            "}"
        )[0]
        self.assertIn("align-items: stretch;", actions_block)
        btn_block = static_css.split(".feature-modal-actions .feature-modal-btn {")[
            1
        ].split("}")[0]
        self.assertIn("align-items: center;", btn_block)
        back_block = static_css.split(".feature-modal-back {")[1].split("}")[0]
        self.assertIn("align-items: center;", back_block)
        # Parehong font-size (0.9rem) na rin para tumugma ang lapad ng text.
        self.assertIn("font-size: 0.9rem;", back_block)
        # Select Design page: naka-inline styles — stretch din ang row.
        template = (
            BASE_DIR / "app" / "templates" / "client" / "select_design_type.html"
        ).read_text(encoding="utf-8")
        self.assertIn("align-items: stretch;", template)
        self.assertIn(
            "display: flex; align-items: center; justify-content: center;",
            template,
        )
