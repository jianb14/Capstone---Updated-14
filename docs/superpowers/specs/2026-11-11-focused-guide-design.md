# Focused feature guide

Superseded by `2026-11-12-spotlight-tour-design.md`: the user requested a read-only Next/Back spotlight tour, replacing task-aware assistance.

Approved by the user: limit guidance to Booking (including status/change requests), Design Canvas and Payments. This replaces the general site tour.

Use a compact, manually started pointer/bubble that follows the actual task: missing inputs, visible existing errors, the current booking step, actual canvas checklist results and available payment actions. Skip completed answers. Never duplicate business validation or submit/pay/save for the user. Advance after change/blur without moving typing focus.

Remove public/auth/profile/review/concern guides, global navbar launchers, hover tips and the large counter/settings card. Local Guide buttons and Close/Escape provide ON/OFF. Nothing starts on page load or login. Keep the AI assistant's existing guide.

Keep the target/focused input usable and unobstructed. Support 320px screens, light/dark, reduced motion, native/custom modal focus/inert, changing booking steps and partial account navigation. Unsupported dialogs stop guidance. Use existing data and validation; no new dependencies or requests.

Verify no guides on unrelated pages, no autoplay, compact bounds/clearance, prefilled answers, input/errors/step progression, actual canvas/payment states, modals, focus and partial navigation. Run browser checks and the full suite; compare the previously recorded baseline failures.
