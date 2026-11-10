# Booking package gallery implementation plan

> Use executing-plans inline. The user approved the gallery design.

**Goal:** Show package samples on demand within the same modal without expanding package cards.

**Architecture:** Replace setupInlinePreviews with setupPackageGallery(root, imagesForCard, clearPackage). Keep existing selection and pricing handlers; synchronize gallery completion through their existing sync calls. Add one sibling gallery panel, hidden outside package preview.

**Stack:** Django templates, vanilla JavaScript, CSS, existing Playwright browser tests.

**Spec:** docs/superpowers/specs/2026-11-10-booking-package-gallery-design.md

Constraints: preserve all unrelated workspace edits, four-step navigation, extras and saved designs, pricing warnings, theme and typography. No new dependencies.

- [x] Update browser regression for compact cards, gallery browsing without selection, Back/Select, image navigation, empty/broken images and scroll/focus. Observe failure.
- [x] Replace shared preview helper and CSS; wire create/edit, reset gallery on navigation and bump asset versions. Update customer help and affected tests.
- [x] Run focused Django/browser checks and inspect phone/desktop screenshots in both themes. Review async paid-change cancellation.
- [x] Record verification, including the previous full-suite baseline failures, without committing unrelated work.
