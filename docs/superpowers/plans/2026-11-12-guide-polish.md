# Guide Visual and Motion Polish

**Goal:** Improve the existing spotlight tour's launchers, layouts and transitions across its supported features.

**Scope:** Guide buttons, feature/dialog header alignment, tour panel styling, entry/step/exit motion. Preserve the approved read-only Next/Back tour, manual launch and Close/Escape. Do not redesign unrelated pages or add backend behavior/dependencies.

**Approach:** Use one neutral, clearly labelled Guide button with a focus icon and consistent 44px hit area. Group calendar actions, align checkout actions, and give modal launchers a deliberate header position. Keep the site's existing type/colors. Add brief synchronized spotlight/panel movement, content fade and entry/exit fades; stop motion for reduced-motion users and during scroll/resize tracking.

## Tasks

- [x] Add a browser regression for requested motion/cleanup and launcher geometry; observe failure against the current version.
- [x] Polish shared button/header styles and dialog placement.
- [x] Add cancellable motion without making navigation or cleanup depend on animation events.
- [x] Inspect supported-feature screenshots at desktop/mobile sizes and both themes; verify reduced motion, rapid navigation/close, keyboard and existing account-menu behavior.
- [x] Obtain independent review, address verified findings, and update usage/verification evidence.

## Constraints

No automatic tour, task coaching, new settings, dependencies, data changes, payment/AI requests or unrelated manual edits. Immediate cleanup on route/context teardown. Scroll and spotlight geometry must stay aligned. This visual/interaction follow-up uses focused browser/system checks; the complete backend suite's previously reproduced failures remain documented separately.

## Result

Implemented shared launchers, aligned calendar/checkout/dialog headers, a separate booking-form control row, responsive Canvas Tools controls, and cancellable entry/step/exit motion. Motion and header-overlap regressions failed before their fixes. Final browser run: **12 passed in 117.983 seconds**. Independent review's CSS-specificity finding was reproduced and fixed; follow-up review found no additional P1/P2 issues. See [verification evidence](../../site-guide-verification.md).
