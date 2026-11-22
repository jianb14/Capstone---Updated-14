# Category uploads and Theme Decor proposal

Status: Approved by the user on November 20, 2026. Implementation authorized, limited to the proposed feature and necessary integrations while preserving existing behavior.

The user separately approved mapping the existing exact Theme Decor inclusions in Package 1-B, Package 2, Package 3, Package 4, and Stand B to the built-in upload category. Their existing blank quantities and optional minimum of zero remain unchanged. Packages without the inclusion receive no new rule.

Customers should upload custom design elements directly inside their matching canvas asset categories. A custom placement should consume the same allowance as a catalog placement in that category. Theme Decor should be a permanent upload-only category for varied decorations, enabled by the selected offer's inclusions.

## Confirmed behavior

The user requested removal of the separate general reference upload area while retaining background upload. Image categories such as Panels and Balloons receive their own upload controls. Theme Decor contains customer uploads without requiring administrator-supplied default images. An offer without Theme Decor shows the category disabled.

The user confirmed that Theme Decor may contain balls, decorated balloons, character props, and other desired decorations. Classification follows the category used for upload. One separately placed image counts as one item in that category, including when several physical objects appear inside the image. An item does not consume two categories at once.

The remaining policies below are proposed implementation choices for approval, rather than additional decisions already made by the user.

## Existing behavior and constraints

- `app/templates/client/design_canvas.html` puts background upload and uncounted general reference uploads in one Uploads tab. A legacy Theme Decor text field sits inside the Styrofoam Name section.
- `static/js/design_canvas.js` tags general uploads as references, caches their thumbnails in browser storage, and excludes references from offer evaluation. The active offer flow hides the legacy Theme Decor field.
- `app/design_validation.py` and `static/js/design_rules.js` count recognized catalog assets. A user-supplied category label cannot turn an uploaded image into a catalog asset.
- `app/offer_editor.py`, `app/design_admin.py`, and `app/design_validation.py` currently expect eligible catalog assets for included categories. An upload-only category needs an explicit supported path through these checks.
- Offer inclusion quantities, required minimums, availability, and the shared balloon color limit already exist. These remain the source of package allowances.
- New bookings currently copy the saved design thumbnail into a booking Design record. That preview does not preserve a per-category custom upload breakdown for administrators.

## Approaches

1. **Category uploads with a built-in Theme Decor category, recommended.** Catalog and custom placements share category allowances. Theme Decor has a stable identity and works without default images. This matches the requested flow, but photo contents and actual production feasibility still require human review.
2. **An ordinary administrator-created Theme Decor category.** Reuses ordinary category administration, but requires setup, permits accidental removal, and needs the same support for categories without images. It does not provide the requested permanent tool.
3. **Keep general uploads and ask customers to classify them afterward.** Retains a central library but adds another classification step and makes it easier to leave required items uncounted. It conflicts with the requested category-first flow.

The user's confirmed direction matches approach 1. This proposal completes its behavior and safeguards.

## Canvas navigation and uploads

Rename the Uploads rail entry to Background and retain its existing fit, fill, replace, and remove controls. Remove the general photo dropzone and general uploads grid from that panel.

Each ordinary image asset category contains an Upload button, catalog assets, and that design's custom images for the category. Styrofoam Name remains its existing text tool. Theme Decor uses the same category accordion structure but displays only its upload control and custom images.

Selecting or dropping a file into a category creates a thumbnail in that category. It does not consume an allowance until the customer clicks or drags it onto the canvas. Show the category and a Custom upload label on these thumbnails. A short item label may default to the filename and be editable for administrator readability.

Keep catalog and custom items visually distinguishable without adding a separate upload workflow. Preserve keyboard access, readable focus states, light and dark themes, and the existing mobile asset sheet. Disabled Theme Decor includes a readable Not included in this package explanation; it must not depend on a tooltip.

Uploading a photo preserves its aspect ratio and transparency. Photographs are not automatically cut out or recolored like an SVG asset. A transparent PNG or WebP is preferable when the customer wants a freestanding prop in the layout.

## Counting and offer limits

| Action | Result |
| --- | --- |
| Upload a file into a category library | No placement counted |
| Place a catalog panel | One Panel |
| Place a custom panel | One Panel from the same allowance |
| Place a decorated balloon uploaded in Theme Decor | One Theme Decor |
| Duplicate a counted placement | One additional item in its original category |
| Delete a placement | Remove its count |
| Undo or redo | Recalculate from the current canvas |
| Upload or replace a background | No inclusion count |
| Upload a collage or photograph containing several props | One placement; physical contents are not automatically counted |

For a two-panel offer, one catalog panel and one custom panel use the full allowance. A third panel receives the existing limit feedback and, where compatible, the existing higher-package suggestion. Custom panels must participate in upgrade compatibility checks as well as ordinary counting.

Use category identity from a server-validated custom upload record, not a customer-editable category name or an invented catalog asset identity. Catalog assets continue through their existing validation. Both sources feed the same per-category counts, required minimums, and maximums.

Invisible, fully transparent, zero-scale, background, and artboard objects do not fulfill required placements, consistent with the existing evaluator. Grouping must preserve the identities of separate placements; a single catalog SVG continues to count once. Do not introduce a new grouping feature.

Drafts may be saved with missing, over-limit, or incompatible items, following the current draft behavior. The evaluation explains what must be corrected. Booking requires a valid current offer and complete required placements within its rules.

## Theme Decor identity and package configuration

Create or adopt one canonical Theme Decor category with a protected built-in identity. Protect it from deletion, renaming, deactivation, or conversion into a balloon category. It contains no administrator-created default assets. Do not create a dummy image just to satisfy catalog readiness checks.

Provision it for the existing offer kinds so administrators can explicitly include it in a Package, Entrance Arch, or Welcome Stand. Provisioning does not add it to any offer. In every kind, inclusion remains an explicit offer rule. Keep the Styrofoam Name built-in behavior separate.

The offer editor controls whether Theme Decor is included, its required minimum, and its optional maximum. For example, a required minimum of one and a maximum of three allows one to three placements. This is an example, not a quantity to assign to real packages.

Preserve existing blank-quantity semantics: Included with no numeric quantity has no canvas maximum. Explain that this is a reference allowance and does not promise unlimited physical decorations. Recommend that administrators set a finite allowance where the package specifies one. Do not invent quantities or impose a new cap on existing offers.

An offer without a Theme Decor inclusion shows the category disabled and cannot accept a Theme Decor placement as a valid booking item. Other categories keep their current inclusion filtering. An active image category that permits customer uploads can be usable without default catalog images; text-only tools still need their actual text preset.

Remove the legacy Theme Decor text field from Styrofoam Name. The existing booking Design Theme field still expresses the overall concept and does not fulfill a Theme Decor placement.

## Uploaded balloons and colors

Quantity follows the upload category. A decorated balloon in Theme Decor consumes Theme Decor only, as the user confirmed. Administrators assess whether a customer has used that category appropriately.

For custom placements in a category marked as using the shared balloon color limit, require the customer to declare the intended balloon colors using the existing palette controls. Store these declarations with the placement. Combine distinct declared colors with catalog balloon colors when evaluating the existing shared maximum, including package upgrade suggestions.

These are declared colors, not automatic pixel analysis. Render them in the booking reference breakdown for administrator review. A custom balloon without its required color declaration cannot satisfy booking validation when the offer has a balloon color limit. Theme Decor does not inherit the Balloons color limit.

## Switching packages

Re-evaluate all placements against the new offer. Preserve the customer's work when an item becomes incompatible or over its new limit. Identify the affected category and show what must be removed or changed before booking. Do not silently delete, reclassify, or promote a custom item into an included category.

Changing to a package without Theme Decor disables further Theme Decor uploads and placements. Existing Theme Decor placements remain visible as flagged draft items until removed or a compatible package is selected. A changed offer's required minimums also take effect immediately.

## Image storage and validation

Keep customer uploads separate from global CanvasAsset records. Uploads must have server-validated image content, an owner, a fixed source category, a readable label, and any declared balloon colors. Use existing configured media storage and installed image handling rather than a new external service.

Proposed file policy: accept JPEG, PNG, and WebP up to 10 MB each, reject invalid or excessive image dimensions safely, and normalize images for canvas use while preserving alpha. Use a maximum working edge of 2048 pixels. Display failed-upload errors beside the affected category and keep successful uploads and the current layout intact.

Persist image identities and category associations when saving a design. Restoring an upload library must work from saved data on another browser or device; browser storage is only a draft convenience. Keep the existing saved-design allowance and overall request limits. Submit stable image references rather than repeating full image bytes in every canvas copy.

Only the owner may attach or reuse their uploads in a design. Administrators may inspect uploads referenced by bookings they can manage. Reject another user's upload, a fabricated upload identity, an inactive category, or a category not allowed by the selected offer. Verify this on the server for upload, evaluation, save reporting, and booking. An invalid placement may remain in a saved draft, but must not count or become bookable.

Deleting a thumbnail removes its library entry; it must not destroy an image still used by a placement, saved design, or booking reference. Retain files while referenced and clean up genuinely unreferenced uploads using the repository's media lifecycle conventions. Cancellation and failed requests must not leave an ever-growing permanent upload pool.

## Booking references and administrator review

Retain the existing pending booking and administrator review flow. Add a category breakdown to the existing customer references area with each custom image, label, category, placement quantity, declared colors when applicable, and the saved layout preview. A repeated image can be displayed once with its placement count.

At booking submission, preserve a snapshot of the submitted layout and custom item breakdown. Later edits to or deletion of a saved design must not change what the booking shows. Booking references must retain access to their images even when the source design or thumbnail is removed. Historical bookings without a breakdown keep their existing preview and do not receive invented metadata.

For customer wording, distinguish Required placements complete from administrator confirmation of availability, materials, size, and feasibility. Custom uploads do not automatically create new catalog items, trigger an extra price, or guarantee availability. Use existing chat, booking review, quotation, and change-request mechanisms if a different item or price must be agreed; do not add a second approval workflow.

If an existing booking's package is later changed through its current edit or change-request flow, retain its submitted reference snapshot and flag a mismatch for administrator attention. Do not silently rewrite it to match the new package. Replacing a booking's canvas through those forms is outside this change.

## Existing data

Adopt an existing exact Theme Decor category when unambiguous; otherwise create the canonical category without deleting categories or assets. Conflicting existing identities or default Theme Decor assets need a migration report and deliberate resolution rather than deletion or reassignment of unrelated content.

Map an existing exact Theme Decor canvas inclusion to the canonical category while preserving its quantity and minimum. An exact Theme Decor service inclusion may be proposed for conversion using its current quantity, with an optional minimum of zero unless an existing rule explicitly requires it. Present such conversions for review before applying them; free-text service descriptions are not automatically canvas items. Do not add Theme Decor to offers that lack the inclusion.

Old general reference images already placed on a saved canvas remain visible and uncounted. Do not guess their categories from their filenames or image content. A customer can use the new category upload flow if they want an old image to count. Browser-only, unplaced cached uploads are not silently recategorized or deleted. Preserve that cache during rollout; the former general library is no longer displayed.

Do not claim the old Theme Decor text field supplies a missing placed item. Preserve any existing saved preferences as text where they already exist, without fabricating images.

## Work to complete after approval

The implementation must reach canvas templates, desktop and mobile behavior, upload persistence, built-in category protection, both offer configuration paths, shared client and server evaluation, package upgrade checks, booking reference snapshots, and administrator reference display. Update affected guidance so it no longer says all customer uploads are uncounted references.

Exact model names, migration structure, helper boundaries, endpoint names, media cleanup integration, and visual spacing are left to the builder using existing repository conventions. These choices must preserve the observable behavior above. No new dependency is expected.

## Acceptance checks

- Catalog and custom panels share a maximum; duplication cannot bypass it, and a compatible upgrade accounts for both.
- Uploading alone does not fulfill a requirement. Placement, removal, undo, redo, reload, and a second browser produce consistent counts.
- Theme Decor works without a default image, is configurable in the offer editor, and is disabled and rejected for booking when absent from the offer.
- Required and optional Theme Decor follow the configured minimum and maximum, including existing blank-quantity behavior.
- Package switching retains draft work and flags incompatible custom items without silent loss.
- Custom balloon color declarations participate in client evaluation, server validation, and package upgrade suggestions.
- Forged metadata and another customer's uploads cannot satisfy inclusions or be attached to a booking.
- Invalid or oversized uploads fail clearly without losing the design; transparent images retain transparency.
- Saved upload libraries restore with their categories, and submitted booking references survive later saved-design edits or deletion.
- Old reference-only canvas images and historical booking previews remain available and uncounted as before.
- Background upload, Styrofoam Name, ordinary catalog counting, offer availability, and the existing booking and payment flow continue to work.
- Desktop and mobile views support upload, placement, disabled feedback, and reference review with keyboard access and both themes.

## Limits

Automatic validation checks identity, declared category, declared colors, and placement allowances. It does not identify physical objects inside photos, verify production cost, or guarantee that a custom item is available. Administrator review remains necessary for those questions. Automatic background removal, AI image classification, physical inventory deduction, automatic custom-item pricing, and a new approval pipeline are outside this proposal.
