"""Regression tests para sa design-canvas UI fixes (save modal, summary,
color split, styro centering).

Sinasaklaw:
- Save button: outline SVG floppy disk, walang
  `prompt(`/`alert(` sa save flow — modal + SweetAlert toast ang gamit.
- Design Summary title: walang `fa-receipt` icon.
- Assets colors: hiwalay na Canvas Color (white/black/light gray + custom)
  at Object Color (dating 10 colors + custom); bilog ang custom pickers.
- Styrofoam Name button: centered ang icon + text.
"""
from pathlib import Path

from django.test import TestCase

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = BASE_DIR / "app" / "templates" / "client" / "design_canvas.html"
CSS = BASE_DIR / "static" / "css" / "design_canvas.css"
JS = BASE_DIR / "static" / "js" / "design_canvas.js"


class DesignCanvasUiTests(TestCase):
    def setUp(self):
        self.html = TEMPLATE.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")
        self.js = JS.read_text(encoding="utf-8")

    def test_save_button_uses_outline_floppy_icon(self):
        self.assertIn("name='save'", self.html)
        self.assertNotIn("fas fa-floppy-disk", self.html)

    def test_save_flow_uses_modal_and_toast_not_prompt_alert(self):
        self.assertIn('id="saveDesignModal"', self.html)
        self.assertIn('id="saveDesignNameInput"', self.html)
        self.assertIn(".canvas-modal-overlay", self.css)
        self.assertIn("openSaveDesignModal", self.js)
        self.assertIn("showCanvasToast", self.js)
        # Walang prompt()/alert() na natitira sa save flow.
        self.assertNotIn("prompt('Enter a name", self.js)
        self.assertNotIn("alert('Design saved successfully", self.js)
        self.assertNotIn("alert('Network error", self.js)

    def test_design_summary_title_has_no_icon(self):
        self.assertIn("<span>Design Summary</span>", self.html)
        self.assertNotIn("fa-receipt", self.html)

    def test_canvas_and_object_colors_are_split(self):
        # Canvas: white / black / light gray + sariling custom.
        self.assertIn("Canvas Color", self.html)
        self.assertIn('data-target="canvas"', self.html)
        self.assertIn('id="customCanvasColor"', self.html)
        # Object: dating 10 colors + sariling custom.
        self.assertIn("Object Color", self.html)
        self.assertIn('data-target="object"', self.html)
        self.assertIn('id="customObjectColor"', self.html)
        self.assertIn("customObjectColor", self.js)

    def test_custom_color_pickers_are_circles(self):
        self.assertIn("#customObjectColor", self.css)
        self.assertIn("border-radius: 999px", self.css)

    def test_styrofoam_button_is_centered(self):
        self.assertIn(".text-preset-card .icon-label", self.css)
        # Ang lumang override na nagpapantay-gilid sa Styro button ay dapat
        # wala na; i-scope ang check sa mismong rule, hindi sa buong file
        # (maraming ibang components ang lehitimong gumagamit ng flex-start).
        start = self.css.find(".text-preset-card .icon-label")
        self.assertNotEqual(start, -1)
        block = self.css[start:start + 400]
        self.assertNotIn("flex-start", block)
        self.assertIn("align-items: center", block)

    def test_no_duplicate_sweetalert_cdn(self):
        self.assertNotIn("sweetalert2@11", self.html)

    def test_color_sync_scopes_by_data_target(self):
        # syncSidebarColorUI(hex, target) accepts a target scope.
        self.assertIn("function syncSidebarColorUI(hex, target)", self.js)
        # Caller passes 'object' when a single object is selected, else 'canvas'.
        self.assertIn("syncSidebarColorUI(activeColorHex, singleObj ? 'object' : 'canvas')", self.js)
        # Object color changes touch customObjectColor, not customCanvasColor.
        self.assertIn("customObjectColor.value = normalized", self.js)
        # Canvas-only swatches are keyed by data-target="canvas".
        self.assertIn('data-target="canvas"', self.html)

    def test_panel_search_light_mode_styled(self):
        # Light theme panel-search: light bg, dark text, gray placeholder.
        self.assertIn('[data-theme="light"] .panel-search', self.css)
        self.assertIn('background: #ffffff', self.css)
        self.assertIn('color: #111827', self.css)
        self.assertIn('color: #9ca3af', self.css)

    def test_selection_toolbar_shadow_is_minimal(self):
        # Base toolbar shadow is minimal (not heavy 0 18px 40px).
        self.assertIn("box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35)", self.css)
        # Light theme shadow is also reduced.
        self.assertIn("box-shadow: 0 4px 12px rgba(0, 0, 0, 0.10)", self.css)
        self.assertNotIn("0 18px 40px", self.css)

    def test_viewport_pan_is_enabled(self):
        # ENABLE_VIEWPORT_PAN is true so pan/zoom interactions work.
        self.assertIn("const ENABLE_VIEWPORT_PAN = true;", self.js)
        # Empty-canvas left-drag pan is wired in mouse:down.
        self.assertIn("isEmptyCanvas", self.js)
        self.assertIn("opt.target === artboard", self.js)
        self.assertIn("isEmptyCanvas && primaryPointer", self.js)
        self.assertIn("opt.e.touches?.length === 1 || opt.e.button === 0", self.js)

    def test_layer_forward_backward_buttons_renamed(self):
        # Capa buttons na ginamit sa template at JS ay na-rename sa layerUpBtn/layerDownBtn.
        # Dapat walang naiiwan na lumang variable names sa HTML at JS.
        self.assertNotIn("layerUpBtn", self.html)
        self.assertNotIn("layerDownBtn", self.html)
        self.assertNotIn("layerUpBtn", self.js)
        self.assertNotIn("layerDownBtn", self.js)
        self.assertIn("layerForwardBtn", self.html)
        self.assertIn("layerBackwardBtn", self.html)
        self.assertIn("layerForwardBtn", self.js)
        self.assertIn("layerBackwardBtn", self.js)
        # Legitimate references sa JS: dapat magkasya sa DOM lookup.
        self.assertIn("layerForwardBtn.disabled", self.js)
        self.assertIn("layerBackwardBtn.disabled", self.js)

    def test_sidebar_toggle_recenters_canvas(self):
        # Regression: syncCanvasAfterSidebarToggle used to call
        # zoomCenter(canvas.getZoom()) which is a no-op (scale ratio 1) and
        # left the canvas off-center in BOTH open and close directions.
        # Now it must centerArtboardAtCurrentZoom() (zoom preserved) so the
        # artboard stays centered regardless of sidebar open/close state.
        self.assertIn("syncCanvasAfterSidebarToggle", self.js)
        self.assertIn("centerArtboardAtCurrentZoom()", self.js)
        self.assertNotIn("zoomCenter(canvas.getZoom())", self.js)
        # Canvas still re-syncs to the dropzone's current width/height on toggle
        # (layout-resize path that triggers the recenter).
        self.assertIn("canvas.setWidth(dropZone.clientWidth)", self.js)
        self.assertIn("canvas.setHeight(dropZone.clientHeight)", self.js)

    def test_locked_text_is_not_editable(self):
        # Locked text objects must set editable:false (movement locks alone
        # do not block enterEditing via double-click).
        self.assertIn("editable: !shouldLock", self.js)
        self.assertIn("exitEditing", self.js)
        self.assertIn("text:editing:entered", self.js)

    def test_selection_toolbar_is_pinned_not_dragged(self):
        # Selection toolbar is a pinned top bar: JS clears legacy inline
        # offsets so canvas pan/zoom never drags it. It is NOT sticky —
        # plain absolute anchor at the top of the dropzone.
        self.assertIn("removeProperty('left')", self.js)
        self.assertIn("removeProperty('top')", self.js)
        start = self.css.find(".selection-toolbar {")
        self.assertNotEqual(start, -1)
        block = self.css[start:start + 400]
        self.assertIn("position: absolute", block)

    def test_layer_forward_backward_labels(self):
        # Forward/backward = distinct outline layer icons with correct tooltips,
        # distinct from Bring to Front / Send to Back. Native `title`
        # tooltips are replaced by styled `data-tooltip` ones.
        self.assertIn('data-tooltip="Bring Forward"', self.html)
        self.assertIn('data-tooltip="Send Backward"', self.html)
        self.assertNotIn('title="Bring Forward"', self.html)
        self.assertNotIn('title="Send Backward"', self.html)
        self.assertIn("name='layer-forward'", self.html)
        self.assertIn("name='layer-backward'", self.html)
        self.assertIn("bringForward()", self.js)
        self.assertIn("sendBackwards()", self.js)

    def test_search_input_has_no_inner_border(self):
        # input[type="search"] UA inner box must be killed in both themes.
        self.assertIn('.panel-search input[type="search"]', self.css)
        self.assertIn("border: 0 !important", self.css)
        self.assertIn("background: transparent !important", self.css)
        self.assertIn('[data-theme="light"] .panel-search:focus-within', self.css)
        # Keep a versioned stylesheet URL without tying the check to an old release.
        self.assertIn("css/design_canvas.css' %}?v=", self.html)

    def test_background_image_is_clipped_to_artboard(self):
        # Cover + clip: uploaded bg never overflows the artboard rect.
        self.assertIn("fitBackgroundImageToArtboard", self.js)
        self.assertIn("clipPath", self.js)
        self.assertIn("syncBackgroundToArtboard", self.js)
        # Cover (Fill) = Math.max scale — hindi pwedeng maliit ang image
        # sa loob ng artboard (may crop sa mismatched edges).
        self.assertIn("Math.max(ARTBOARD_W / img.width", self.js)

    def test_background_fill_fit_toggle(self):
        # 2-button segmented toggle (Fill/Fit) sa Uploads panel:
        #  - Fill (cover): Math.max + centered + clipPath (dating behavior).
        #  - Fit (contain): Math.min, centered, walang clip — buong image
        #    kita; ang bakante ay canvas color.
        # Hindi kailanman ini-stretch (uniform scale lang) at may hint
        # text na nagpapaliwanag ng crop. Monochrome ang active pill.
        self.assertIn('data-bg-fit="cover"', self.html)
        self.assertIn('data-bg-fit="contain"', self.html)
        self.assertIn('id="bgFitHint"', self.html)
        self.assertIn("bgFitMode", self.js)
        self.assertIn("normalizeBgFitMode", self.js)
        self.assertIn("updateBgFitToggleUI", self.js)
        self.assertIn("Math.min(ARTBOARD_W / img.width", self.js)
        self.assertIn("'_bgFitMode'", self.js)
        self.assertIn(".bg-fit-btn", self.css)
        self.assertIn(".bg-fit-btn.active", self.css)
        self.assertIn('[data-theme="light"] .bg-fit-btn.active', self.css)
        # Monochrome: walang accent color sa bagong toggle.
        self.assertNotIn("#7c3aed", self.css)
        # Pantay ang FA icon at text sa loob ng buttons — line-height
        # normalization sa parehong flex items (Styro button fix pattern).
        icon_start = self.css.find(".bg-fit-btn i {")
        self.assertNotEqual(icon_start, -1)
        icon_block = self.css[icon_start:icon_start + 200]
        self.assertIn("line-height: 1", icon_block)

    def test_canvas_navbar_is_not_sticky(self):
        # Main toolbar is a normal relative grid row (sticky was reverted).
        self.assertIn(".canvas-main-toolbar", self.css)
        start = self.css.find(".canvas-main-toolbar {")
        self.assertNotEqual(start, -1)
        block = self.css[start:start + 400]
        self.assertIn("position: relative", block)
        self.assertNotIn("position: sticky", block)

    def test_sidebar_header_and_search_are_not_sticky(self):
        # No sticky anywhere in the sidebar: header + search scroll normally.
        self.assertNotIn(".sidebar-panel .sidebar-panel-header", self.css)
        self.assertNotIn(".sidebar-panel .panel-search", self.css)

    def test_upgrade_modal_uses_shared_pattern(self):
        # Upgrade modal migrated from inline styles to the shared
        # canvas-modal pattern: light-mode + tighter radius included.
        self.assertIn('id="upgradeModal" class="canvas-modal-overlay"', self.html)
        self.assertIn("canvas-modal-upgrade", self.html)
        self.assertNotIn("border-radius: 24px", self.html)
        self.assertIn("openUpgradeModal", self.js)
        self.assertIn("closeUpgradeModal", self.js)
        self.assertIn(".canvas-modal-upgrade", self.css)
        self.assertIn("border-radius: 16px", self.css)
        self.assertIn('[data-theme="light"] .canvas-modal-upgrade-icon', self.css)
        self.assertIn("css/design_canvas.css' %}?v=", self.html)

    def test_layers_sidebar_tab_exists(self):
        # Rail button + panel + filter + list + empty state.
        self.assertIn('data-panel-target="layersPanel"', self.html)
        self.assertIn('id="layersPanel"', self.html)
        self.assertIn('id="layersList"', self.html)
        self.assertIn('id="layersEmpty"', self.html)
        self.assertIn('id="layersCountBadge"', self.html)
        self.assertIn('data-layers-filter="all"', self.html)
        self.assertIn('data-layers-filter="overlapping"', self.html)
        self.assertIn(".layers-list", self.css)
        self.assertIn(".layer-row", self.css)
        self.assertIn(".layer-drag-handle", self.css)
        self.assertIn('[data-theme="light"] .layer-row', self.css)

    def test_layers_panel_logic(self):
        # Stable IDs + persist + reverse order (top = front) +
        # moveTo reorder + artboard excluded + bg locked row +
        # locked rows not draggable with lock icon at right.
        self.assertIn("ensureLayerIdentity", self.js)
        self.assertIn("makeLayerId", self.js)
        self.assertIn("defaultLayerName", self.js)
        self.assertIn("refreshLayersPanel", self.js)
        self.assertIn("scheduleLayersRefresh", self.js)
        self.assertIn("moveLayerObjectToRow", self.js)
        self.assertIn("canvas.moveTo(obj,", self.js)
        self.assertIn("getLayerObjects", self.js)
        self.assertIn("!obj._isArtboard", self.js)
        self.assertIn("'_layerId'", self.js)
        self.assertIn("'_layerName'", self.js)
        self.assertIn("'#ci-lock'", self.js)
        self.assertIn("Unlock the layer to reorder it.", self.js)
        self.assertIn("is-locked", self.js)

    def test_layers_drag_and_selection_fixes(self):
        # Whole row is the drag source (no 6-dot-only dragging), drop
        # markers are inset so the bottom row's glow is never clipped,
        # reorder clamps to index 1 when no background exists (objects
        # could previously never reach the very bottom), and Fabric's
        # default blue selection box is replaced by a neutral white
        # (theme is monochrome — no blue/violet accent allowed).
        self.assertIn("li.draggable = !isLocked && !isBg", self.js)
        self.assertIn("clearLayerDropMarkers", self.js)
        self.assertIn("box-shadow: inset 0 -3px 0 0 #ffffff", self.css)
        self.assertIn("box-shadow: inset 0 3px 0 0 #ffffff", self.css)
        self.assertIn("const minIndex = hasBg ? 2 : 1", self.js)
        self.assertIn("selectionBorderColor: '#ffffff'", self.js)
        self.assertIn("borderColor: '#ffffff'", self.js)
        self.assertNotIn("#7c3aed", self.css)
        # Control style is re-applied on object:added so objects restored
        # from JSON never fall back to Fabric's default blue border.
        self.assertIn("Re-apply the themed control style on every add", self.js)
        # Action buttons must not start a row drag.
        self.assertIn("if (event.target.closest('.layer-action-btn')) li.draggable = false", self.js)

    def test_toolbar_buttons_use_custom_tooltips(self):
        # Native `title` tooltips (slow, unstyled browser bubble) are
        # replaced by CSS-only `data-tooltip` popups on all three toolbars.
        self.assertIn("[data-tooltip]:hover::after", self.css)
        self.assertIn('data-tooltip="Bring Forward"', self.html)
        self.assertIn('data-tooltip="Lock / Unlock"', self.html)
        self.assertIn('data-tooltip="Clear Canvas"', self.html)
        self.assertNotIn('id="layerForwardBtn" class="ctrl-btn icon-only" title=', self.html)
        self.assertNotIn('id="contextLockBtn" title=', self.html)

    def test_tooltips_have_arrow_and_per_area_placement(self):
        # Bawat tooltip ay may arrow (::before) na nakaturo sa button:
        # rail = right, main/selection = bottom, context/layers = top.
        self.assertIn("[data-tooltip]:hover::before", self.css)
        self.assertIn("rotate(45deg)", self.css)
        self.assertIn(".canvas-tool-rail [data-tooltip]:hover::after", self.css)
        self.assertIn("left: calc(100% + 10px)", self.css)
        # Rail arrow = kaliwa + ibaba borders (hindi taas+kaliwa) — dapat
        # nakaturo sa kaliwa ang tip, hindi pataas.
        rail_arrow = self.css.split(
            ".canvas-tool-rail [data-tooltip]:hover::before {"
        )[1]
        rail_arrow = rail_arrow.split("}")[0]
        self.assertIn("border-left: 1px solid", rail_arrow)
        self.assertIn("border-bottom: 1px solid", rail_arrow)
        self.assertIn("border-top: none", rail_arrow)
        self.assertIn(".canvas-main-toolbar [data-tooltip]:hover::after", self.css)
        self.assertIn(".selection-toolbar [data-tooltip]:hover::after", self.css)
        self.assertIn("top: calc(100% + 8px)", self.css)
        # Ang context toolbar (lumulutang) ay nasa taas ang tooltip.
        self.assertIn(".object-context-toolbar [data-tooltip]:hover::after", self.css)
        # Ang main toolbar ay nasa ibabaw ng selection toolbar (higher
        # z-index) para hindi matakluban ang tooltip nito.
        self.assertIn("z-index: 60", self.css)
        # Ang selection toolbar ay hindi na nagki-clip ng tooltips sa baba.
        start = self.css.find(".selection-toolbar {")
        self.assertNotEqual(start, -1)
        block = self.css[start:start + 800]
        self.assertIn("overflow: visible", block)



