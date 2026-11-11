# Balloorina Guide Implementation Plan

Historical plan. The current implementation follows `2026-11-11-focused-guide.md`.

> **For agentic workers:** Use executing-plans to implement this plan in the current session. Steps use checkbox syntax for tracking.

**Goal:** Add a smooth, optional contextual guide without interrupting normal visits.

**Architecture:** One shared nonmodal guide component, scoped CSS, a small page-specific content map, and a vanilla JavaScript controller. Reuse AccountPages lifecycle events and existing template shells. Work in the current checkout so the user's local application receives the change; preserve unrelated manual artifacts.

**Tech Stack:** Django templates, browser APIs, existing Playwright/Chrome verification tools.

**Spec:** `docs/superpowers/specs/2026-11-11-site-guide-design.md`

## Global constraints

- No autoplay or per-visit chooser; manual Next/Back and immediate Close.
- Hover tips default OFF, with boolean-only per-browser storage and graceful denial fallback.
- No new dependency, database migration, backend action, live transaction, or admin UI change.
- Keep the site's palette/type, match the reference's pointer/bubble interaction, and support light/dark/mobile/reduced motion.

## Review focus

- Replaced account content must not leave a stale target, timer, focus return, or duplicate controller.
- Hidden steps and modal overlays must not receive guidance for background controls.
- Native-dialog top layers, narrow screens and browser zoom must not clip the callout.
- Existing tooltip handlers and Escape listeners must not compete with active guidance.
- Denied storage and rapid Next/Close/scroll must leave the site usable.

## Task 1: Browser regression contract

- [x] Add `app/test_site_guide_browser.py` using the existing opt-in StaticLiveServerTestCase/Playwright pattern.
- [x] Exercise actual guide markup/controller in a controlled browser fixture: no autoplay, navigation, persistence, keyboard, narrow/reduced-motion, storage failure and context cleanup.
- [x] Run with `RUN_SITE_GUIDE_BROWSER=1`; observe failure because the guide does not exist.

## Task 2: Shared guide and context content

- [x] Create `components/site_guide.html`, `components/site_guide_button.html`, `static/css/site_guide.css`, `static/js/site_guide_content.js`, `static/js/site_guide.js`.
- [x] Content entries are `{target, title, text}`. Resolve current account page from `data-account-page`, otherwise the shared component's server-provided route name. Prefer the active modal and visible booking step; skip missing/hidden controls.
- [x] Controller owns launch/Next/Back/Close, tips storage, hover/focus delay, focus restoration, and frame-coalesced positioning. Tours never trigger target actions.
- [x] Wire the existing client/auth shells and navbar; add an in-context booking launcher.
- [x] Run the browser contract and fix failures before expanding coverage.

## Task 3: Real-page integration and polish

- [x] Add real-route browser checks for guests/customers, partial account navigation, booking and canvas.
- [x] Verify viewport bounds, pointer transitions, mouse/keyboard/touch, both themes and reduced motion; inspect screenshots.
- [x] Run Django system checks, targeted existing tests and the complete Django suite with `Project.test_settings`.
- [x] Review the final diff and record behavior, validation and any material limits in `docs/site-guide.md`.

## Execution record

- Started: 2026-11-11. User selected delegated implementation; no further design confirmation needed.
- Ruling: use immediate explanation text rather than character typing; retains the pointer animation while avoiding reading delays and screen-reader churn.
- Ruling: implement in place; no worktree or unrelated commits are needed for this additive local change.
- Verification: the expected missing-feature test failed before implementation. Baseline account workspace/table tests: 10 tests, 3 opt-in skips, passed.
- Independent review found custom-modal inert containment, edit-dialog launchers, password-recovery mapping and checkbox-pseudo-element interference. Reproduced the interaction failures, fixed them, and added regressions. Follow-up review found no further material issues.
- Visual checks caught the global light-theme heading/small overrides and narrow-screen header overflow. Scoped the guide's text colors and moved its mobile entry into the drawer. The existing account-menu browser regression now passes.
- Browser validation: `RUN_SITE_GUIDE_BROWSER=1 RUN_ACCOUNT_MENU_BROWSER=1` with the two browser modules: **8 tests passed** (89.529s).
- JavaScript syntax checks and Django system checks passed.
- Full-suite run: **1,512 tests in 448.784s; 11 failures, 21 errors, 220 skips**. Failures involve existing request/session fixtures, stale template assertions, booking rules/concurrency, and design-delivery migration/schema isolation. A baseline rerun of all affected modules uses the original HEAD versions of every modified template through a locmem loader; it never overwrites working files.
- Baseline proof: 220 affected-module tests reproduced 10 failures/10 errors; running the existing migration cleanup before design-delivery email tests reproduced the remaining 1 failure/11 errors. An automated Counter comparison confirmed that all 32 full-suite failure/error entries exactly match the combined baseline. Names and evidence: `docs/site-guide-verification.md`.
- Completed: shared guide, contextual content, responsive launchers, persisted optional tips, review, screenshots and regression verification. No deployment or unrelated test fixes were made.
