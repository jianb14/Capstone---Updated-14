# Theme Decor Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Allow admin Theme Decor images alongside existing customer uploads.

**Architecture:** Reuse CanvasAsset CRUD and signed catalog evaluation. Keep the
protected category and its readiness without default assets, while making images
in that category ordinary catalog assets.

**Tech Stack:** Django, Django templates, Fabric.js, existing Playwright tests.

**Spec:** docs/superpowers/specs/2026-11-23-theme-decor-catalog-design.md

## Global Constraints

No new fields, migrations, dependencies, default images, or layout. Preserve
customer upload privacy, package inclusion enforcement, and Styrofoam protection.

## Review Focus

- An excluded offer must reject catalog Theme Decor as well as uploaded decor.
- Catalog and uploaded decor must share one allowance, including after reopening.
- Hidden and unavailable admin images must follow ordinary asset eligibility.
- Deleting a Theme Decor asset must leave its protected category usable.
- An empty admin catalog must still allow customer Theme Decor uploads.

## Task 1: Enable existing catalog administration and placement

- [x] Add behavior tests in `app/test_theme_decor_catalog.py`; verify failures
  caused by the form/model/catalog restrictions.
- [x] Remove those restrictions in `app/catalog_forms.py`,
  `app/canvas_builtins.py`, `app/design_validation.py`, and the legacy admin asset
  chooser/availability decorator in `app/design_admin.py`.
- [x] Update the built-in explanatory message, upload hint, and offer-editor
  help text to describe both sources. Update the superseded default-image
  prohibition assertion in `app/test_canvas_uploads.py`.
- [x] Verify the new tests and related admin, built-in, upload, offer, and
  booking-theme regressions, plus JS tests, checks, and migration drift.

## Task 2: Verify the real designer flow

- [x] Add/run a focused browser check for included/excluded Theme Decor,
  admin-image placement, customer upload placement, quota counting, and reload.
- [x] Request independent diff review; resolve any material findings and record
  verification results here. Leave changes reviewable in the current checkout.

## Execution record

- Four new integration tests failed first because the admin form excluded Theme
  Decor, then passed after enabling catalog images. Two additional legacy-admin
  tests failed first because those pages still excluded/rejected the category.
- Final focused Django run: **70 passed**, covering the new catalog tests,
  uploads, admin catalog, built-ins, category upload flows, offer editor, and
  booking-theme policy. Used isolated SQLite `Project.test_settings`; no
  development database writes. Log: ignored
  `.booking-followup-check/theme-decor-catalog-backend.log`.
- New Edge/Playwright test: **1 passed**. Verified excluded-category hiding,
  catalog-above-upload ordering, mixed 2/2 count, save/reopen, desktop light/dark,
  mobile saved-design restoration, and no horizontal overflow. This catalog
  test uses the existing Use original action; background inference is covered
  by its separate feature tests. The initial mobile attempt toggled an already
  active Assets tab after resizing; reloading the saved design at phone width
  makes the responsive initialization explicit.
- Four existing Node scripts passed: design rules, upgrades, upload
  serialization, and booking-theme inclusion.
- Django check, migration drift check, and diff whitespace check passed. No
  schema or dependency changes.
- Independent read-only review found the same legacy chooser/POST restriction.
  Fixed it with the two legacy RED-to-GREEN regressions above; no other findings.
  Legacy offer-import exclusions remain because they preserve explicit package
  inclusions. Standard saved-catalog behavior after hiding/deleting an asset
  is unchanged.
- Inspected desktop and mobile screenshots in the system temporary directory.
  The user subsequently requested committing and pushing this change on the
  current branch, `feat/multi-design-booking`. The unrelated untracked manuals,
  archives, and diagram files are excluded.
