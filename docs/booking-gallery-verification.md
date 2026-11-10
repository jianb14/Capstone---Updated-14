# Booking package gallery verification — 2026-11-10

The create and edit booking forms keep four steps. Package-card selection no longer opens or inserts images. View sample setups replaces the package list inside the existing booking modal with a gallery; it does not select the viewed package.

The gallery shows the current price and inclusions, a bounded image area, Previous/Next controls, Back to packages and Select this package (Select this item for extras). Back/Escape restore list scroll and focus. Selection uses the existing handlers, including paid-change confirmation; cancelling preserves the old selection and returns keyboard focus to Select. Missing/broken images keep the gallery usable. Remove package still permits switching to a solo entrance arch.

## Checks

- 113 focused Django tests pass (29.944 seconds), covering preview payloads, design preferences, form parity, catalog, venue/duration, customer modals and saved designs.
- Seven combined browser tests pass (277.465 seconds), including compact-card height, viewing without selection, gallery image controls, empty/broken images, scroll/focus restoration, four-step back/next, pricing totals, extras/solo mode, saved-design paths, paid-change cancellation and catalog ordering.
- Service/login continuation browser test passes (98.329 seconds).
- After fixing cancelled-warning focus restoration, all four gallery/saved-design/paid-change browser tests pass again (109.670 seconds), including the new focus assertion and 844px mobile viewport checks.
- After refining the preview action into an icon-and-chevron row, both create/edit gallery browser tests pass (89.668 seconds). Checked desktop, tablet and 320/390px mobile screenshots; card height stays unchanged when a package is selected.
- After restoring the compact left/right footer and fixing date/start-time hint readability, both browser tests pass (84.689 seconds). Checks cover matching action text sizes, horizontal alignment, footer height, full-opacity sentence-case hints, and at least 4.5:1 text contrast in both themes.
- Screenshots checked at desktop/tablet and 320/390px mobile widths in light/dark themes. Mobile checks use an 844px viewport height and assert the gallery fits without outer modal scrolling, even with twenty inclusions. Screenshots: `.booking-followup-check/package-gallery/`.
- JavaScript syntax and whitespace checks pass. UI lint has zero failures and four warnings for existing shadow rules.

The preview action now sits compactly on the left of the footer, with Remove package on the right. Both use the same small text size and reduced vertical spacing. The image icon and chevron remain, with hover underline and a keyboard focus outline instead of a full-width hover fill.

Date and start-time prerequisite hints now use full opacity, sentence case and 12px helper text. They keep the theme's muted color instead of error red. Browser checks assert at least 4.5:1 contrast against the actual background in light/dark themes.

Package-card bottom padding is reduced to 8px in both forms; other card padding is preserved. This final spacing-only adjustment was checked in the CSS diff without repeating the browser suite.

Both templates use CSS version `20261110compact2` and JavaScript version `20261110galleryrow1`. No dependencies or backend pricing/booking policy changed. Generated local static copies have been refreshed; no deployment was performed.

The earlier full repository run had 11 failures, two SQLite concurrency errors and 208 skips; see [the previous verification report](booking-four-step-verification.md) for names and baseline comparison. Those unrelated failures were not changed as part of this gallery revision; the full suite was not repeated for this frontend revision.
