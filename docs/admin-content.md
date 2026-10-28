# Admin content workspaces

Packages, Gallery and Canvas Assets share the neutral controls, focus rings and theme tokens used by Customer Concerns. Each collection has its own tab, search, filters, stable pagination (8 rows by default; Show 4 or 8), and an empty state without an empty table header.

Add, edit and view actions open dialogs. Filtering, tab changes, pagination, saves and deletion use authenticated same-origin requests without reloading the document. Browser Back restores the list filters. Failed requests keep the current list or form draft visible.

Successful creates, edits, single deletions and bulk deletions show the shared top-right notification used by Admin Users and Concerns. This covers packages, entrance arches, welcome stands, gallery images/categories and canvas assets/categories. Operational failures also show an error notification above the active modal; field and upload validation stays below its control. Notifications appear only after the server confirms the result. A failed list refresh does not turn a successful save into a save error.

Create and edit dialogs keep Save and Cancel in a separate footer outside the scrolling body, without a top divider or explanatory status text. Save buttons explicitly submit their associated form. The offer dialog shares Gallery's buttons, checkbox appearance and focus ring; invalid fields retain the normal background with red borders and inline errors. Descriptions, notes, quantities, color limits and preview photos are marked optional where applicable.

Select rows using the first column, or select all deletable rows on the current page. The bulk bar shows the selection count. Deletion requires a confirmation and a CSRF-protected POST. A stale or protected selection is rejected in full; it never partially deletes the selected rows. Bookmarked legacy delete URLs also require POST.

Built-in canvas assets and categories cannot be edited or deleted. Gallery categories must be empty before deletion. Canvas categories must have no assets or offer requirements. Removing offers preserves booking records and clears optional catalog references through the existing model relationships.

Gallery creation supports up to 4 photos per submission. Canvas assets use one image per record. Both validate actual image contents and a 10 MB per-image limit. Replacement uploads are optional when editing. The offer dialog has Details, Inclusions, Photos and Visibility tabs, retaining its two-preview limit and authoritative inclusion/design rules. Validation opens the tab containing the first invalid control.

Canvas management has only Assets and Categories. Migration `0116_remove_canvas_labels` removes the unused label collection and relationship while preserving assets and images; it first copies legacy label names to assets with blank names. Historical migrations are retained. Apply migrations when deploying these changes.

The category setting “Uses the shared balloon color limit” identifies balloon categories only. Panels and other decorations should leave it off; the design builder applies an offer's shared color allowance to categories marked as balloons.

Field errors appear directly below controls with a small gap, red text and accessible descriptions. Required labels have a red asterisk. Forms validate on the server as well as in the browser; uploads and draft values remain selected when a submission is rejected.

Verification: `app.test_admin_catalog`, `app.test_admin_catalog_browser` (opt in with `RUN_CATALOG_BROWSER=1`), plus the existing offer editor, canvas builtin, gallery and design requirements suites.

Home, About, Service, and Guidelines & Policies now use the same workspace controls and dialogs. Existing page URLs and sidebar links stay available. Page introductions, section headings, support hours, story and mission photos are edited in section dialogs; ordered features, booking steps, FAQs, values, milestones, services and policy sections use searchable tables. The initial display order matches the public page. Visibility, sorting, tabs, Show 4/8, pagination, view details and mutations use fetch without a document reload. Clear search and empty states share the Concerns appearance.

These four editors omit KPI/summary cards and statistic preview panels. Their section editors and content tables remain available. Create/edit visibility controls have a separate Visibility label above the checkbox row. Public Home/About statistics still update automatically.

Create/edit forms have a fixed Save/Cancel footer, optional labels, required asterisks, neutral focus rings and inline red validation. Story, mission and service photos use a one-photo dropzone with actual image validation and a 10 MB limit. Replacement uploads are optional; existing photos can be removed explicitly. Successful saves and single/bulk deletions use the shared top-right feedback. A failed save retains input values and selected images. Deletion requires confirmation and POST, including legacy item delete URLs. Bulk selections are validated in full before removal.

Home event/rating/satisfaction figures and About customers served remain automatic. Only daily support hours are editable, within 1–24. Section saves update only that section's fields. Legacy Home/About items attached to another content record remain manageable because the public pages display them too. Default content is seeded only when creating a missing page, so removing the last collection item does not recreate it.

Policies are separated into Booking Guidelines, Terms & Conditions and Privacy Policy. Each has an introduction and ordered sections. Emailing active customers is an explicit opt-in on save or delete; unchanged content sends no notice. Email failures are reported without undoing the saved policy. Notification links point to the policy that changed. No schema migration is needed for this redesign.

Verification: `app.test_admin_page_content`, `app.test_admin_page_content_browser` (opt in with `RUN_PAGE_CONTENT_BROWSER=1`), existing policy notification and Home/About statistics suites. Browser coverage checks async CRUD, tabs/history, pagination, bulk deletion, retained drafts, focus rings, fixed modal footers and layouts at 1440, 768, 390 and 320 pixels in both themes.
