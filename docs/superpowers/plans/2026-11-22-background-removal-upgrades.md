# Asset Background Removal and Upload Upgrade Fix

> Use superpowers:executing-plans inline and request a fresh final review.

**Approved scope:** Automatic background removal for newly selected category images, a transparent preview with Use original, balloon color declarations retained, and the uploaded-balloon upgrade confirmation bug. The Background tab retains the entire image. Previously saved images remain unchanged.

**Architecture:** An owner-authenticated preview endpoint validates the offer/category and normalizes a bounded image, then runs a local CPU segmentation model and returns a private, uncached PNG without creating a library record. The existing preview dialog shows progress, cutout, Use original, and retry. Only the reviewed selection is sent to the existing save endpoint. Existing alpha is preserved. Failure cannot silently save an unreviewed result. A cached CPU model with bounded concurrency prevents simultaneous heavy inference.

**Dependencies:** rembg CPU with a small u2netp model. Prepare the model locally and document deployment preparation. No photo service credentials or new database fields.

- [x] Add failing upgrade browser coverage for a 3-color upload under a 2-color offer, confirm upgrade and placement, cancel and revalidation.
- [x] Fix confirm validation to pass the same upload registry used for suggestions.
- [x] Add failing preview tests for private access, malformed/oversized files, preserved alpha, no stored records and segmentation failure.
- [x] Add local removal helper, preparation command, dependencies and validated PNG endpoint; run a real model smoke check.
- [x] Extend per-file preview to all categories with automatic processing, abort/cancel, retry and original choice; preserve balloon declarations.
- [x] Run backend/JS/browser regressions, inspect previews in both themes/mobile, request review and record operational limits.

**Review focus:** cancelled processing does not save images; original pixels and alpha are retained on opt-out; non-balloon uploads no longer skip the preview; saved/booked images remain immutable; upgrade confirmation rechecks the full current design with signed upload identities.

## Execution evidence

- Upgrade RED: actual Edge test remained on Package 1-A after confirming the offered Package 1-B for a 3-color uploaded balloon. Fixed confirmation by supplying the same upload registry passed to initial suggestions. GREEN browser checks cancel, retry, confirmed Package 1-B, one placed photo and Ready to book.
- Preview RED/GREEN: model helper tests failed before implementation, then passed alpha preservation, RGBA output/empty foreground rejection, endpoint access/validation, model failure recovery and no library persistence during preview.
- Installed rembg CPU2.0.76 and prepared verified u2netp model (about4.6MB) locally. Actual official plant-photo smoke generated PNG with alpha0..255. Actual synthetic balloon test retained center alpha254 and transparent corner0. No external photo processing service is used.
- Browser coverage: automatic asset preview, balloon declarations, cutout save, original save, unavailable model/retry, cancel, per-file isolation, existing transparent photos, immutable edits/history, save/reopen/mobile, unchanged Background-tab uploads and upgrade confirmation.
- Fresh reviewer verified async generations/abort, owner and category guards, immutable existing references and upgrade revalidation. Found output PNG size edge (valid JPEG could generate >10MB PNG). Added a failing random-RGBA regression (16,802,182 bytes), then resized only oversized generated PNGs until within the existing save contract, preserving alpha. Follow-up review is clean.
- GREEN combined regression:81 backend/browser tests passed in214.601 seconds, including actual prepared-model endpoint smoke. Latest four helper tests including the new size bound passed separately. Three JavaScript behavior scripts, syntax checks, Django checks, migration consistency, diff whitespace and pip dependency checks passed.
- Operational notes are in `docs/asset-background-removal.md`; a fresh deployment must install requirements and run prepare_background_remover. Existing library images are unchanged; this applies to new category uploads. No migrations were required.
- Final fresh verification after the size fix: all9 background-removal tests passed in11.426 seconds with the real CPU model enabled, including cutout size, alpha, owner validation, concurrency recovery and failure handling. No full-system suite was repeated for this scoped change.
