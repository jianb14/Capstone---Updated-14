# Balloorina Error Pages Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan in this session.

**Goal:** Deliver branded English 403, 404 and 500 pages with verified HTTP behavior.

**Architecture:** Shared standalone error template, explicit Django handlers and middleware for existing direct HTML 403 responses. No context processors or database dependencies in rendering.

**Tech Stack:** Existing Django 5, Django templates, CSS, local theme script, Playwright.

**Spec:** docs/superpowers/specs/2026-11-10-error-pages-design.md

## Global Constraints

- English copy, existing monochrome branding, no new dependencies.
- Preserve JSON/AJAX bodies and error status codes; do not alter authorization.
- Work in the current checkout; no commits, deployment or public crash routes needed.

## Review Focus

- Explicit forbidden responses must receive the same design as raised PermissionDenied.
- CSRF responses retain 403 and never reveal diagnostic reasons.
- Existing JSON and AJAX responses remain unchanged.
- Database/context processor failures must not break the error renderer.
- POST failures must not offer a link that repeats the submission.

## Task 1: Error handling and presentation

**Files:** app/test_error_pages.py, app/error_pages.py, app/templates/errors/http_error.html, app/templates/errors/_http_error_styles.html, Project/urls.py, Project/settings.py.

- [x] Add request-level tests for the review conditions and watch the missing branding fail.
- [x] Implement handlers and response middleware, register them, and build the shared responsive template.
- [x] Run the focused tests until green.

## Task 2: Verification and review

**Files:** app/test_error_pages_browser.py, this plan.

- [x] Run browser checks with real rendered responses for both themes, keyboard links, all three statuses, mobile/tablet/desktop, disabled scripts and unavailable assets.
- [x] Run Django checks and the complete project test suite; report any failures precisely.
- [x] Request an independent code review and address substantive findings.
- [x] Record verified results and limitations here.

## Results

13 focused error-page tests pass. Final combined permission, API, account, request-protection and error-page/browser regression run: 137 tests, 132 passed and 5 optional tests skipped. Browser matrix covers six viewport sizes in both themes, local fonts/logo, contrast, keyboard navigation, recovery links and unavailable scripts/assets. Design inspector: zero failures; its three typography warnings are expected for a standalone error screen with a prominent status number rather than a working dashboard.

Full suite: 1,475 tests, 13 failures, 2 SQLite concurrency errors, 203 skipped. All 15 failing test labels and counts reproduce when the new middleware is disabled and original error/CSRF handlers are restored in an isolated verification process. No unrelated fixes were made. See docs/error-pages-verification.md for commands, failure names and limits.

Independent review found a missing Vary header for negotiated responses; this and unsafe retry URL edge cases were reproduced with failing tests and fixed. Final review reported no remaining substantive findings. No deployment or commits performed.
