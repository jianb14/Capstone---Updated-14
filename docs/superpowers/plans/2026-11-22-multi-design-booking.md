# Multi-design Booking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Book one package, one entrance, and one welcome stand from My Designs as one validated, correctly priced booking.
**Architecture:** A focused `app/design_booking.py` owns composition, saved-design resolution, presentation payloads and signed quote identity. Existing booking pricing, transactions, design snapshots, forms and account-list behavior are extended in place. A separate selection controller and stylesheet implement the approved mockup against actual user designs.
**Tech Stack:** Django, vanilla JavaScript/CSS, existing Django/Node tests, existing local Playwright installation.
**Spec:** `docs/superpowers/specs/2026-11-22-multi-design-booking-proposal.md`; approved visual reference: `docs/ui-previews/my-design-booking/`.

## Global Constraints

- Stand requires package OR entrance; at most one saved design per category.
- Entrance uses add-on price with package, solo price without package. Fees remain once per booking.
- No merged canvases, new cart/database schema, dependency installation, or payment/status redesign.
- Preserve historical prices and unchanged legacy/custom selections; validate new catalog compositions.
- Work on feature branch in the user's current folder, preserve unrelated files, leave changes reviewable without committing/pushing.
- User has approved execution; continue inline through all tasks, then request one independent code review.

## Review Focus

- Catalog/readiness changes between selection and POST must return a reviewable quote/error, retaining event inputs.
- A second snapshot/storage failure must not leave a partial booking or orphaned new images.
- Search, pagination, deletion, and source design edits must not resurrect invalid selected designs.
- Changed catalog compositions in pending edits and reviewed amendments must enforce category/dependency rules without repricing unchanged history.
- Form reset, Back, replayed submission, mobile focus, and unavailable sessionStorage must preserve valid behavior.

### Task 1: Trusted selection and saved-design booking

**Files:** Create `app/design_booking.py`, `app/test_multi_design_booking.py`; modify `app/views/bookings.py`, `app/design_reference_snapshot.py`, `app/booking_changes.py`.
**Interfaces:** `resolve_design_selection(user, ids, lock=False)` returns validated ordered entries and quote metadata; `selection_payload(entries)` returns JSON-safe typed amounts/names/previews; `validate_catalog_selection(label)` validates resolved known catalog compositions and permits wholly legacy custom labels.
- [x] Add failing integration tests for six combinations, duplicate kinds/IDs, foreign/malformed IDs, stand-only, tampered totals, multi-ID GET, quote changes, atomic snapshots, and normal create/edit/amendment composition validation.
- [x] Run new tests with `--settings=Project.test_settings --noinput`; confirm failures expose current last-ID-only/stand-only behavior.
- [x] Implement typed composition resolution, quote identity/checks, canonical labels, save all typed snapshots and clean failed image writes. Retain singular GET/POST compatibility.
- [x] Run targeted tests plus existing requirements, pricing/theme, change-request, snapshot suites; expected green.

### Task 2: Approved My Designs selection UI

**Files:** Modify `app/views/designs.py`, `app/templates/client/my_designs.html`, `static/js/my_designs.js`; create `static/js/design_booking_selection.js`, `static/css/design_booking_selection.css`; update relevant library tests.
**Interfaces:** Server JSON provides the account's design identities, readiness, category, applicable rates, and protected preview URLs. Selection controller stores only account-scoped IDs and rebuilds from current server metadata.
- [x] Add failing tests for typed card payloads, stand wording, summary actions, and complete/draft selection; add a small Node check for dependency/price transitions if extracted pure helpers warrant it.
- [x] Build cards plus desktop summary/mobile sheet matching the approved mockup, using real assets. Preserve editor, menus, search, sorting and pagination. Emit `design-library-updated` after AJAX replacement.
- [x] Verify selection survives filters/Back, duplicates are disabled with explanations, removal clears dependent stand, and unavailable designs cannot continue.

### Task 3: Booking handoff, quote review and references

**Files:** Modify `app/templates/client/booking/booking_page.html`, existing customer/admin reference templates and relevant help text.
**Interfaces:** Repeated `design_id`/`user_design_id` values, signed quote, typed selection payload. Old `prefilled_design` remains a boolean/first-design compatibility alias.
- [x] Add failing tests for typed initialization, all preview images, quote-update response and component labels.
- [x] Initialize the actual package/add-on/stand/solo state after reset, protect fixed selections, retain the saved-design event->preferences shortcut and correct summary/back behavior.
- [x] Handle quote changes without submission, clear local selection only on success, and label snapshots by component with legacy fallbacks.
- [x] Run backend regressions and JavaScript syntax checks; expected green.

### Task 4: Browser verification and independent review

**Files:** Create `app/test_multi_design_booking_browser.py`; update verification notes and this plan/ledger.
- [x] Run actual Django pages with isolated test DB/media and existing Playwright, covering desktop/mobile light/dark, search/page changes, selection locks, signed handoff, review and actual one-booking/three-snapshot submission.
- [x] Check stale quotes, keyboard sheet focus, browser errors, normal booking and old single-design path.
- [x] Run targeted complete regression suite, Django checks and migration drift check. Inspect screenshots.
- [x] Dispatch fresh reviewer against uncommitted diff, spec and plan. Address important findings with failing tests then fixes. Record final evidence and any limitations; do not merge or push.
