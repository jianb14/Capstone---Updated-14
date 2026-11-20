# AI Launcher Invitation Implementation Plan

**Goal:** Add the agreed typewriter invitation to the existing AI chat button.
**Architecture:** One aria-hidden label inside the existing button, scoped CSS, and a small standalone timer controller using the existing chat expanded state.
**Tech Stack:** Django templates, CSS, vanilla JavaScript, Playwright/Edge.
**Spec:** `docs/superpowers/specs/2026-11-20-ai-launcher-invite-design.md`

## Global Constraints

Hold 2 seconds; wait 8 seconds between cycles; wait 60 seconds after cycle 3. Keep the icon stationary. Preserve the existing click handler, accessible name, and chat APIs. Respect reduced motion. No dependencies.

## Review Focus

Verify the minute-long pause, interruptions during partial typing, keyboard focus after chat closes, reduced-motion changes, and mobile clipping.

## Task 1: Invitation

- [x] Add browser verification using virtual time: typing, 2-second hold, deletion, 8-second gaps, 60-second rest, and interaction pauses. Run it and confirm the missing invitation fails.
- [x] Add the label, style it in the existing palette, and implement the cancellable timer. Invalidate timers while chat is open, the tab is hidden, or the launcher is being used.
- [x] Run the targeted browser test plus existing AI chat presentation and guide browser checks. Inspect screenshots in both themes at desktop, tablet, and mobile widths.
- [x] Run Django checks, JavaScript syntax validation, and diff checks. Record the results.

Execution: in the current requested workspace, preserving unrelated user files. The user's `okay go` authorizes implementation of the agreed design; no additional approval round is needed.

## Verification

- Missing invitation: both new browser tests failed before implementation.
- Pointer bridge: regression reproduced before the fix; independent Edge review verified ordinary bubble clicks after the fix.
- Final command: `RUN_DESIGN_BROWSER=1 .venv/Scripts/python.exe manage.py test app.test_ai_invite_browser app.test_ai_chat_ui_browser app.test_ai_design_guide_browser --settings=Project.test_settings --noinput --verbosity 1` (set the environment variable with PowerShell). All 5 tests passed in 130.706 seconds.
- Screenshots cover 320, 390, 768, and 1440px in light/dark themes. Artifacts and logs: `.booking-followup-check/ai-invite-*`.
- Django checks, `node --check static/js/ai_invite.js`, and `git diff --check` passed.
- Existing launcher verification now expects a stationary AI icon and the new invitation; admin support keeps its tooltip and lift checks.
- No live AI inference or production database was used. The full application test suite was outside this UI change's verification scope.

## Follow-up: hover stability and direction

The user reported hover competing with typing and requested a text-only invitation growing from right to left. The root cause was pointer/focus events calling the full reset function: entry replaced partial text with the complete sentence, and exit erased it and restarted the wait.

The controller now preserves its pending step and remaining delay through pointer/focus pauses. Lifecycle changes still reset independently. The text keeps normal reading order while a fixed right edge makes each longer prefix extend leftward; the caret is on the left. Removed the decorative sparkle and bumped both asset versions to `20261120invite2`.

New browser regressions failed against the previous behavior. Coverage now includes exact typing resume, hover during erasing, preservation of the three-cycle rest, no extra SVG, and fixed right-edge text bounds. The independent reviewer verified exact remaining delays in typing, holding, and erasing, plus the pointer bridge and text geometry.

Final follow-up verification: all 6 tests in the same three browser modules passed in 99.007 seconds. Log: `.booking-followup-check/ai-invite-hover-final.txt`. The virtual clock setup now pauses one second after installation to avoid trying to pause in the past; existing launcher checks assert frozen text instead of assuming hover completes the sentence. JavaScript syntax and diff whitespace checks passed.

## Follow-up: bubble width follows each letter

The user clarified that the bubble itself must grow and shrink with the typed prefix. Removed the invisible full-sentence grid reservation and horizontal entrance translation. The bubble now uses max-content width from the visible characters, with no horizontal or width tween. Its right edge remains beside the icon; the left edge expands by each character. CSS asset version is `20261120invite3`; the JavaScript controller is unchanged.

The new two-letter width test failed before the fix (145.125px), then all 3 invitation browser tests passed in 14.224 seconds. They cover growth, reverse shrinkage, hover/timing, theme/mobile fit, and the original rest interval. Screenshots: `.booking-followup-check/ai-invite-two-letters.png` and `ai-invite-full-text.png`. Independent Edge verification at 320px measured 43px for two letters, 137px for the full sentence, then 43px again, with a fixed right edge. Log: `.booking-followup-check/ai-invite-width-verified.txt`. Diff whitespace checks passed. Verification was scoped to the invitation for this CSS-only correction.

## Follow-up: stationary glyphs and visible keystrokes

The user still found the motion visually like sliding. Prefix insertion in a right-anchored bubble was moving every existing glyph whenever a new character appeared. For the requested right-to-left typing, the controller now inserts the next letter at the left instead: `t`, `nt`, `ent`, through the completed readable label. Existing letters stay fixed. Deletion removes the leftmost letter and retracts the bubble. Component-local kerning is disabled for consistent glyph positions.

Typing is deliberately slower at 85ms per keystroke (previously 55ms). The 2-second hold, 30ms deletion, 8-second gap, and 60-second third-cycle rest remain. The caret stays solid during typing/deletion and blinks only while holding the completed text. Both asset versions are `20261120invite4`.

A failing regression captured the prior prefix behavior. Final verification: all 3 invitation browser tests passed in 15.511 seconds, including unchanged final-glyph position, true right-to-left insertion, fitting/shrinking bubble, hover pause/resume, lifecycle cancellation, and theme/mobile checks. JavaScript syntax and diff checks passed. Log: `.booking-followup-check/ai-invite-keystrokes-final.txt`.

The browser test records the actual typing/deletion cycle into `.booking-followup-check/ai-invite-keystrokes.gif` and a six-frame contact sheet `ai-invite-keystrokes-sequence.png`. Both the primary agent and independent reviewer inspected the recorded sequence. The complete application test suite was not rerun for this local animation correction.

## Final widget adjustments

- Match invitation padding/corners to admin tooltip: 8px vertical, 12px horizontal, 9px radius, no forced minimum height. Direct Edge rendering verified matching 36px height in both themes at 320px and 1440px. CSS invitation version: `20261120invite5`.
- Replace the AI launcher icon with a 24px minimal robot face. Direct Edge rendering verified bounds and accessible button naming in light/dark themes.
- Increase customer Admin Support panel width from 440px to `min(500px, calc(100vw - 48px))`. Height and existing mobile rules are retained. Direct browser comparison across 7 widths (320, 390, 520, 521, 768, 1440, 1920px) verified unchanged height/mobile bounds and no clipping in both themes. Support CSS version: `20261120width1`.

Pre-commit verification of the final combined widget changes: all 6 browser tests across `app.test_ai_invite_browser`, `app.test_ai_chat_ui_browser`, and `app.test_ai_design_guide_browser` passed in 92.576 seconds. Django system check, JavaScript syntax check, and diff whitespace check passed. Log: `.booking-followup-check/widget-precommit.txt`. Verification was scoped to these UI changes; the full application test suite was not run.
