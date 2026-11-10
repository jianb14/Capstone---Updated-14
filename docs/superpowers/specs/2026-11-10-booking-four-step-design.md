# Four-step booking form

The four-step order remains current. The inline-preview interaction below has been superseded by `2026-11-10-booking-package-gallery-design.md` at the user's request.

Status: Four-step order approved by the user; user delegated the preview interaction choice. Proceed with the recommended inline preview.

## Intent

Check event details before asking customers to choose and customize a package. Make sample setups available while selecting a package rather than requiring a separate preview step.

## Design

Both create and edit booking use Event Details → Select Package → Design Preferences → Review & Confirm. Existing required-field, availability, location, design, upload, pricing and submission checks remain in place. Going back preserves entered values and selections.

Clicking a package card selects it and expands its sample images beneath its details. Clicking the selected card again closes or reopens its preview without deselecting the package. Selecting another package closes the previous package preview. Selection and expansion have separate accessible states and support keyboard interaction. A separate Remove package action preserves the ability to switch to a solo entrance arch. Existing sample images and missing-image feedback are reused. Extras retain their selection rules and show their own samples without changing the selected package.

Cards retain the current visual style, light/dark themes and responsive grid. Expansion uses the existing image renderer; no new dependency or generated imagery is needed.

## Approaches

- Recommended: inline expandable sample images, keeping comparison and selection together.
- Alternative: a separate preview popup, adding another overlay within the booking modal.
- Remove: the standalone Preview step, which repeats the selection without collecting information.

## Scope and verification

Update both form templates, shared preview behavior/styles, navigation and progress, customer-help instructions, and affected tests. Preserve catalog and saved-design entry points. Verify forward/back navigation, invalid first-step blocking, selection and expansion independently, extras, missing/broken images, review totals, and mobile/desktop light/dark rendering.

No backend schema, booking pricing policy or payment-flow changes.
