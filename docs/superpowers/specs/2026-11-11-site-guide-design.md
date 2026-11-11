# Balloorina Guide

Superseded by `2026-11-11-focused-guide-design.md` after the user's usability feedback.

The user delegated the final choice and implementation after reviewing the alternatives. Use a manually started guide with an animated pointer and user-paced Next/Back. Never start a tour or ask whether to start one on load, reload, login, or navigation.

## Approaches

- Automatic tour: close to the reference, but interrupts repeat visits; rejected.
- Hover explanations only: lightweight, but does not reproduce the reference's guided pointer.
- **Chosen:** manually started contextual tours, plus optional hover/focus explanations disabled by default. The user controls pacing and can stop immediately.

## Experience and scope

- A compact Guide button in the guest/customer navigation, and inside the booking form, starts a tour of the current visible context.
- A nonmodal callout shows Balloorina Guide, progress, a short title/explanation, Back, Next/Done and Close. A separate visual pointer glides to the target without moving the real cursor or consuming clicks on the page.
- Hover tips have an explicit switch; save only this boolean in localStorage (`balloorina-guide-tips`). Persistence is per browser. Failure to access storage leaves an in-memory setting and never breaks the page.
- Cover public navigation/pages, authentication, booking/calendar and visible booking steps, account/profile/bookings/payments/reviews/concerns, designs/canvas, AI and support launchers. Tips explain actions, never initiate them. Use existing policy/price displays rather than duplicating numeric policies.
- Account navigation, detached targets, changed booking steps, and newly opened modal contexts dismiss obsolete guidance. A closed tour never automatically resumes.
- On phones use the same callout with touch controls and no decorative cursor. Respect reduced motion. Text is immediate, not typewriter text, so the user can read at their own speed.
- Accessible names, visible focus, Escape dismissal, restored launcher focus, preserved aria-describedby, viewport-safe positioning, light/dark styling, and no duplicate existing tooltips over a guide target.

## Boundaries

No AI requests, dependencies, database changes, payments, submissions, admin-dashboard changes, or production data mutations. Existing user/admin manual artifacts are unrelated work and must be preserved.

## Verification

Browser tests must exercise no autoplay, Next/Back, cancellation, saved tips across reload/navigation, storage denial, focus/Escape, touch/reduced motion, changed/removed targets, native dialogs, and partial account navigation. Real-route browser checks cover guest/customer pages, booking and canvas. Run Django checks and the project suite, reporting any failures by name. Inspect screenshots at desktop/tablet/mobile widths and both themes.
