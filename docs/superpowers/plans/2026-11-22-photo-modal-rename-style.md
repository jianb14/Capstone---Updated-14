# Photo Color Modal Correction

**Scope:** Follow the actual Rename modal in My Designs for typography, surface, close control and footer buttons; remove delayed checkbox feedback and style the internal scrollbar in both themes. Preserve upload/save/cancel and color-limit behavior.

- [x] Reproduce checkbox computed styles with normal motion and inspect focus overrides.
- [x] Add browser assertions for immediate checked rendering, Rename-sized controls, centered responsive dialog and themed scrollbar.
- [x] Correct only scoped photo-dialog CSS and cache version.
- [x] Run photo upload/edit regression, JS checks and visual review in both themes.

**Reference:** `static/css/my_designs_workspace.css:94` through `:114`: padding28, radius20, title21/600, close36 with18px SVG, footer42px/10x16/radius10.

**Root cause:** The first focused light checkbox test reproduced background rgb(249,250,251) instead of checked ink rgb(17,17,17). The generic light `input:focus` rule was overriding the checked background with `!important`. It was a visual focus conflict; checked state itself was immediate. Scoped checked/focus rules and transition-free check indicators resolve this without changing upload behavior.

**Review:** Fresh read-only review confirmed cascade, focus-visible, color-scheme, scrollbar and Rename sizing. Applied its minor exact-title-color correction. Inspected desktop light and mobile dark screenshots.

**Final verification:** Both category-upload browser cases passed (78.005 seconds), with normal motion enabled for the photo case, immediate focused check styling in both themes, preview/edit/retry/cancel, counts, limits, undo/redo, saved reuse and mobile coverage. JS upload serialization and design-rule checks, Django system checks and diff whitespace checks passed. No database changes. Full-system suite not repeated for this CSS-only correction.


**Selection toolbar follow-up:** Reproduced native disabled=true with opacity1 and pointer cursor. Added a scoped disabled appearance (opacity .4, not-allowed cursor) and stylesheet cache bump; existing native selection gating is retained. Regression verifies catalog picker enabled and upload picker disabled/dimmed, including light/dark and mobile assertions.
