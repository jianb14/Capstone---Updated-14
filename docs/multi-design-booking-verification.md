# My Designs multi-design booking verification

Pre-push verification (November 23): all 47 tests in `app.test_multi_design_booking`, `app.test_customer_booking_modals` and `app.test_multi_design_booking_browser` passed with `Project.test_settings` and `RUN_MULTI_DESIGN_BROWSER=1` (72.747s). The saved-selection JavaScript storage self-check and staged whitespace check also passed. Log: `.booking-followup-check/pre-push-multi-design.log`.

## Inside-image badges and customer reference viewer (November 23)

Wizard preview badges now sit within the image bounds. My Bookings reference thumbnails also show only the stored offer name, without category prefixes or the literal question-mark separator. Custom designs and uploaded reference images use accessible buttons that open a native image dialog above Booking Details. Escape/close restores thumbnail focus while leaving Booking Details open; closing the parent also dismisses the viewer. Failed full-size image loads show a retry explanation. Narrow reference grids use two columns.

Verification: 11 tests passed (29.915s): the real-browser booking handoff, quote review, submission and reference-viewer scenario plus the customer-modal endpoint suite. Browser assertions cover inside-image badge bounds at 1440/768/390/320px, exact reference names, no new tab/navigation, Escape/close focus restoration, and viewer overflow at 1440/390/320px in light/dark. Desktop light badge and mobile dark viewer screenshots were visually inspected. JavaScript syntax and diff whitespace checks passed. Evidence: `.booking-followup-check/reference-modal-red.log`, `reference-modal-green.log`, and `multi-design-booking/reference-viewer-*`.

## Booking selection presentation follow-up

The wizard's selected-design panel now reuses the request-change notice treatment and shared form palette. Names display without redundant category prefixes; entrance pricing mode remains on its own muted line. Custom-design preview captions are neutral offer-name badges. The preview grid fits two columns on narrow screens.

The real-browser handoff, updated-quote review and single-booking submission scenario passed (21.686s), with added badge/rate assertions and overflow checks at 1440, 768, 390 and 320px in light/dark mode. Screenshots at the first three widths are in `.booking-followup-check/multi-design-booking/selected-designs-*` and `preview-badges-*`; desktop light and mobile dark were visually inspected. Test output: `.booking-followup-check/booking-selection-badges.log`.

## Delete flow follow-up

Successful deletion now refreshes the library in place instead of reloading the document, so the welcome intro is not replayed. The refreshed server markup updates cards, pagination, saved count, statistics and the creation-limit notice/button. Search and category filters are preserved; deleting the final card on a later page clamps the displayed page and URL together. Deleted selections are removed immediately, including a stand that loses its last valid package/entrance. Existing entrance pricing is recalculated by the shared selection renderer.

Regression coverage includes a document marker proving no navigation occurred, a filtered deletion at the saved-design limit, dependent stand removal, last-page deletion on a narrow dark viewport, and a failed refresh followed by retry. A failed refresh reports that deletion succeeded while the list/count still need refreshing. Tests use an isolated database and temporary media; no customer designs are deleted during verification. The original flow failed the new no-reload regression (`delete-design-red.log`).

Final verification: all six real-browser scenarios passed (54.631s), including the two delete regressions and the existing light/dark selection, restored-page validation and booking handoff checks (`.booking-followup-check/delete-design-final.log`). JavaScript syntax and the saved-selection storage self-check also passed. An earlier suite run redirected the existing restored-page scenario to login; its isolated rerun passed, followed by the clean six-test rerun. No authentication behavior was changed.

## Selection UI follow-up

Further refinement uses the existing `AppToast` top-right component instead of custom selection notifications. The stand's rate caption is omitted, the saved-count subtitle is restored, and the search field expands into the available toolbar space with no reserved clear-button padding when the clear control is hidden. Empty summary icons are subdued; remove icons are 16px and the modal close icon is 18px. The responsive dialog clips its outer frame and scrolls only its inner body, leaving the compact header/close control outside the scrolling area. View booking uses the same SVG arrow language as Continue. Four browser scenarios and 39 targeted regression cases passed after these changes; an additional control-focused run verifies the shared toast and exact icon sizes.

The user's subsequent UI feedback is implemented: sort labels stay on one line without crowding their chevron; selected cards use one subtle border that stays stable on hover; selected buttons use a quiet `Selected` state; disabled selection buttons keep their colors on hover; and each visual checkbox is now an accessible, independently clickable toggle synchronized with its card button. Selection feedback is a temporary 3.5-second message outside document flow instead of a persistent line above the cards.

Summary empty slots reuse the starting-point picker's SVG category artwork. Remove/close controls use SVG X icons and a neutral hover fill without changing size. Continue uses an aligned SVG arrow. The responsive summary has a sticky close/header and a thin themed scrollbar.

The stand's `Design complete` badge still means its canvas requirements are satisfied; booking it requires a package OR valid solo entrance. The badge does not authorize a standalone stand booking.

Follow-up verification: 39 targeted backend/library tests passed. The final four-scenario browser suite passed (45.619s), including stable X dimensions and auto-cleared feedback. It covers light/dark at 1440, 1024, 768, 390 and 320px, checkbox select/unselect, hover state equality, dropdown label height, responsive SVG controls and scrollbar, plus the existing booking handoff and quote scenarios. Logs and screenshots: `.booking-followup-check/multi-design-polish*`.

Date: November 22, 2026 (Asia/Manila)

Approved design: `docs/superpowers/specs/2026-11-22-multi-design-booking-proposal.md`.
Approved visual reference: `docs/ui-previews/my-design-booking/`.
Implementation plan: `docs/superpowers/plans/2026-11-22-multi-design-booking.md`.
Implementation branch: `feat/multi-design-booking`.

## Implemented behavior

- One package, one entrance, and one welcome stand at most, combined into one event/booking. A stand needs a package OR a valid solo entrance. Canvas panel quantities still follow the selected package's inclusions.
- Entrance add-on price with a package; solo price otherwise. Configured complimentary extras remain allowed; a zero solo entrance rate does not enable standalone entrance booking. Logistics and overtime are charged once per booking.
- Desktop selection summary and mobile dialog, real design previews, clear category restrictions, account-scoped tab selection, and selection retention across search, category filtering, sorting and pagination. Rename updates the selected design name too.
- Restored browser pages refresh catalog/readiness metadata. Unavailable selections cannot continue; missing selector handoffs return an actionable library message.
- Typed saved-design initialization and all references through the existing event -> design preferences -> review flow. Old single-design URLs remain supported.
- Server validates identities, ownership, individual canvas readiness, category uniqueness and dependency rules. Signed quotes cover component content and fee policy. New multi-ID submissions without a quote receive a review response. Updated item/fee quotes preserve entered event details and require another review.
- Each design becomes its own independent canvas/image/upload snapshot with category, source identity, offer and applied component amount. Customer/admin references retain labels even when no thumbnail exists.
- New files are tracked through the outer submission transaction/receipt and cleaned up on failure. Duplicate submissions do not create extra bookings or snapshot sets.
- Pending note-only edits preserve recorded component prices and applicable fee terms; amendments preserve retained mode-specific unit prices. Changed combinations are checked at submission and quote issuance. Literal plus signs and mode words in catalog names are resolved as catalog names.
- Local selection is cleared only when its IDs match the completed saved-design booking; normal bookings do not clear another selection.

## Automated evidence

| Check | Result |
| --- | --- |
| Local PostgreSQL affected-suite run | 406 tests, OK, 2 optional browser skips; six verified pre-existing source assertions excluded explicitly by the local runner. |
| New actual-page browser scenarios | 3 tests, OK, using isolated SQLite/media and installed Chrome. |
| Existing single-design/normal four-step browser scenarios | 2 tests, OK; separately enabled after the PostgreSQL run. |
| Focused price/snapshot/template-mirror regression run | 39 tests, OK. |
| Targeted selection/history/theme/lead-time run | 58 tests, OK before the final literal-name regression was added. |
| Node completion-storage checks | PASS: matching completed IDs clear; empty/normal and different selections are preserved; malformed storage does not throw. |
| Django system checks | No issues. |
| Migration drift check | No changes detected. No schema migration is required. |
| JavaScript syntax / Python compilation | Passed. |
| `git diff --check` | Passed. |

Primary backend command:

```text
python .booking-followup-check/multi-design-booking/run_postgres.py --exclude-baseline-static
```

The local runner uses a fresh, explicitly named disposable PostgreSQL database on localhost, retaining the test settings' temporary media and in-memory email transport. It does not run against the application's data database. Its teardown terminates only sessions belonging to that exact disposable database when necessary. The disposable database left by an initial browser teardown was also removed.

Browser command:

```text
RUN_MULTI_DESIGN_BROWSER=1 python manage.py test app.test_multi_design_booking_browser --settings=Project.test_settings --noinput
```

Legacy browser command also passed with both tests enabled:

```text
RUN_BOOKING_FOUR_STEP_BROWSER=1 python manage.py test app.test_booking_four_step_browser --settings=Project.test_settings --noinput
```

The repository's existing local Playwright installation was supplied through `PYTHONPATH`; no dependency was installed. External browser requests are blocked; the font stylesheet is fulfilled with the existing local Montserrat font for screenshots.

Browser scenarios cover all three selected categories; duplicate locks; rename; AJAX search/category changes/pagination; desktop/mobile light/dark rendering; 320/390/768px overflow checks; mobile dialog/Escape/focus; removing the last base; actual event/preferences/review navigation; changed entrance AND logistics rates; a 409 review response; the corrected final total; and a successful single booking with three references. Another scenario restores a stale page after deleting the selected design and confirms that it cannot proceed. A third checks complimentary extras and unavailable zero-price solo entrance.

Screenshots and execution logs are under `.booking-followup-check/multi-design-booking/`. Screenshot artwork comes from isolated test fixtures, not customer designs.

## Existing source assertion failures

The following six assertions also fail when supplied the original HEAD template/JavaScript sources. They assert older cache suffixes, markup and inline handlers. They were not changed or suppressed in repository tests; the broad local verification runner excludes them explicitly after the baseline comparison:

- `test_css_cache_bust_updated`
- `test_custom_pickers_no_focus_autoopen_and_sturdy_close`
- `test_unavailable_calendar_light_gray_and_blocked_icon`
- `test_edit_modal_instant_time_guards_present`
- `test_past_date_validation_in_both_validators`
- `test_edit_time_fields_revalidate_on_change`

Baseline and current evidence: `availability-baseline.log` and `availability-current-final.log` in the verification artifact directory. The additional missing-package partial-edit regression found during work was fixed; the final lead-time tests pass.

## Independent review

One fresh-context reviewer inspected the application diff, new files, approved spec and plan. No Critical findings. The Important findings about historical prices, quote/fee review, transaction-wide file cleanup, selection parsing, complimentary extras, legacy amendment validation, storage clearing, restored metadata and missing-thumbnail labels were addressed with regression coverage. The keyboard-focus finding was treated as Important and fixed. No deferred review findings.

Implementation decisions: keep the user's current workspace on a feature branch; preserve legacy single-ID direct submissions while requiring reviewed quotes for new multi-ID submissions; use deterministic signatures so semantic retries retain duplicate protection; and preserve historical amounts for unchanged components and pricing modes. Existing normal booking policies, payment/approval workflows and submitted reference history remain in use.
