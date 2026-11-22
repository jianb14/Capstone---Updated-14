# Proposal: Multiple Saved Designs in One Booking

Date: November 22, 2026 (Asia/Manila)

Status: Approved for implementation on November 22, 2026. The user approved the proposal and then the interactive mockup in `docs/ui-previews/my-design-booking/`, and explicitly instructed implementation.

## 1. Layunin

Sa My Designs, makakapili ang customer ng hanggang tatlong saved designs para sa iisang event at booking: isang Package, isang Entrance Arch, at isang Welcome Stand. Susundin nito ang existing booking conditions at ang existing entrance solo/add-on prices.

Ang category limit ay para sa bilang ng saved designs sa booking. Hindi nito nililimitahan sa isang physical panel ang package: kung kasama sa Package 2 ang dalawang panels o sa Package 3 ang tatlong panels, susundin pa rin ang inclusions at canvas requirements ng package na iyon.

## 2. Actual na nacheck sa system

| Bahagi | Current behavior | Epekto sa proposal |
| --- | --- | --- |
| Normal booking selection | Tig-isang package, entrance, at stand ang selection state. | Ito ang category limits na dadalhin sa My Designs. |
| Stand requirement | `selectedPackageName !== null || soloModeAddon !== null`. May guard sa availability ng cards at sa stand click handler. | Package O solo entrance ang kailangan; hindi kailangang pareho. |
| Entrance pricing | `AddOn.price` kapag may package; `AddOn.solo_price` kapag walang package. Ang entrance na walang usable solo price ay hindi selectable bilang solo sa normal booking UI. | Gagamitin ang catalog rates, walang bagong discount percentage. |
| Fees | Items subtotal + isang booking logistics fee + isang booking overtime fee. | Hindi imumultiply ang fees sa dami ng designs. |
| Normal booking steps | Event Details -> Select Package -> Design Preferences -> Review & Confirm. | Pananatilihin ang existing event, venue, schedule, preferences, at review checks. |
| Saved-design booking | Isang `design_id` sa URL at isang `user_design_id` sa submission. Ang saved offer ay fixed; pagkatapos ng Event Details, pumupunta sa Design Preferences. | Palalawakin ang handoff sa maraming designs at pananatilihin ang saved-design shortcut. |
| Saved-design initialization | Lahat ng saved offer kinds ay inilalagay sa `selectedPackageName`, gamit ang standalone offer price. | Kailangang ilagay ang package, entrance, at stand sa kani-kanilang tamang state. |
| Saved-design submission | Isang design ang nire-revalidate at ginagamit para i-override ang submitted offer at price. | Kailangang i-validate at i-price ang buong combination. |
| Design references | Maraming `Design` records ang puwedeng iugnay sa isang `Booking`; may canvas/image snapshots at existing template loops. | Magagamit ang existing storage; hindi kailangan ng bagong cart table. |
| Existing booked prices | May `fee_policy_snapshot.catalog_items` at display helper para manatili ang booked quote. | Pananatilihin ang recorded unit prices at total pagkatapos ma-submit. |

Relevant sources: `app/templates/client/booking/booking_page.html`, `app/templates/client/my_designs.html`, `app/views/bookings.py`, `app/views/common.py`, `app/design_validation.py`, `app/design_reference_snapshot.py`, `app/booking_changes.py`, and `app/booking_themes.py`.

### Napatunayang gaps sa current saved-design submission

Sa isolated SQLite test database, gamit ang existing design fixtures:

- Stand-only saved design submission: tinanggap ng endpoint at nakagawa ng isang booking. Ang test stand na 1,200 plus logistics na 100 ay naging 1,300. Current behavior ito, hindi ang desired rule.
- Tatlong repeated `user_design_id` values para sa package, entrance, at stand: huling ID lang ang ginamit, kaya stand lang at isang reference ang nasave.

Ibig sabihin, hindi sapat ang magdagdag lang ng checkboxes. Kailangan ding ayusin ang request handling at server validation.

## 3. Approaches

| Approach | Paano gagana | Tradeoff |
| --- | --- | --- |
| A. Select designs sa My Designs (recommended) | Pipili ng package/entrance/stand cards, makikita ang selected combination at subtotal, saka magpapatuloy sa booking. | Malinaw ang comparison at presyo. Kailangan ng maliit na selection summary at persistence habang nagsi-search o nagpapalit ng page. |
| B. Book Now, saka pumili ng kasama | Magsisimula sa isang design, saka magdadagdag ng ibang saved designs sa chooser. | Mas malapit sa current per-card entry, pero may dagdag na chooser at mas mahirap makita ang buong selection habang nagko-compare. |

Recommendation: A. Ito ang direktang tumutugon sa pagpili ng tatlong designs mula sa My Designs. Hindi kailangan ng persistent shopping cart o pinagsamang malaking canvas.

## 4. Confirmed booking conditions

| Combination | Allowed | Items subtotal |
| --- | --- | --- |
| Package | Yes | Package price |
| Entrance | Yes, kung available ang solo booking nito | Entrance solo price |
| Package + Entrance | Yes | Package price + entrance add-on price |
| Package + Stand | Yes | Package price + stand price |
| Entrance + Stand | Yes, kung available ang solo booking ng entrance | Entrance solo price + stand price |
| Package + Entrance + Stand | Yes | Package price + entrance add-on price + stand price |
| Stand only | No | Kailangan ng package O entrance |
| Empty selection | No | Kailangan ng package O entrance |
| Dalawang package designs | No | Maximum one package design |
| Dalawang entrance designs | No | Maximum one entrance design |
| Dalawang stand designs | No | Maximum one stand design |
| Parehong design ID nang paulit-ulit | No | Duplicate submission |

Lahat ng napiling saved designs ay kailangang pag-aari ng current customer, available ang offer, at pasado sa sariling canvas requirements. Hindi ibabase ang category sa design name o sa label na ipinadala ng browser.

## 5. Proposed customer flow

### My Designs

- Pananatilihin ang existing cards, thumbnails, editor, search, sorting, pagination, at create-design modal.
- Papalitan ang per-card booking action ng `Select for Booking`. Kapag selected, magiging `Remove from Booking`.
- Ipapakita ang category at offer name para malinaw kung package, entrance, o stand ang card.
- Kapag may napiling design sa isang category, disabled ang select action ng ibang cards sa parehong category, na may paliwanag. Maaaring alisin ang current selection bago pumili ng kapalit. Walang silent replacement.
- Stand selection is enabled only kapag may valid selected package o solo entrance. Kapag wala, makikita ang helper na `Choose a package or entrance arch first`. Puwede pa ring i-edit at i-save ang stand design.
- Ang complete stand card ay `Design complete` na may requirement hint; hindi ipapakitang puwedeng i-book nang mag-isa. Ang incomplete design ay may existing draft/continue-editing behavior.
- May selection summary na nagpapakita ng hanggang tatlong slots, thumbnail, design/offer name, applicable unit price, remove action, items subtotal, at `Continue to Booking`.
- Ipapaliwanag na ang logistics at overtime ay kukuwentahin sa booking matapos ang venue at schedule; hindi tatawaging final total ang items subtotal.
- Ang `Continue to Booking` ay enabled lang kung valid ang selection.

Text sketch ng information at actions, hindi pa final visual layout:

```text
Selected designs
Package:  [thumbnail] Package 1-A / My Birthday Setup   [Remove]
Entrance: [thumbnail] Entrance Z / My Entrance         [Remove]
Stand:    [thumbnail] Stand Z / My Welcome             [Remove]

Items subtotal: [package + entrance add-on + stand]
Logistics and overtime are calculated during booking.
[Continue to Booking]
```

### Pagbago ng selection

- Kapag nagdagdag ng package sa existing solo entrance selection, gagamitin ang entrance add-on price.
- Kapag tinanggal ang package at naiwan ang entrance, gagamitin ang entrance solo price. Maaaring manatili ang stand dahil may entrance pa.
- Kapag tinanggal ang entrance at may package pa, maaaring manatili ang stand.
- Kapag tinanggal ang huling package/entrance, automatic ding aalisin ang selected stand at may malinaw na inline message. Ito ang kaparehong dependency behavior ng normal booking UI.
- Kung hindi na puwedeng i-book nang solo ang entrance, hindi magpapatuloy ang combination na walang package. Magpapakita ng actionable message; walang zero-price fallback.
- Ang updated amounts at dahilan ng price change ay makikita agad bago magpatuloy.

### Search, sorting, pagination, at Back

Pananatilihin ang selected IDs at minimal display metadata sa browser tab, scoped sa logged-in account. Hindi mawawala ang selection kapag nag-search, nag-sort, o nagpalit ng page. May remove action sa summary kahit hindi visible ang selected card.

Browser state is a convenience only; hindi iyon ang trusted source ng ownership, readiness, category, o presyo. Irerevalidate ang selection sa booking handoff at submission. Kapag may unavailable/deleted/changed design, kailangang maayos muna ang selection. Hindi tahimik na aalisin ang isang design at itutuloy ang ibang combination.

Iki-clear ang local selection pagkatapos ng successful booking o explicit clear action. Ang failed submission at normal Back navigation ay magpapanatili ng selection at event inputs.

### Booking form

Saved designs -> Event Details -> Design Preferences -> Review & Confirm -> isang booking.

Panatilihin ang current saved-design shortcut na nilalampasan ang catalog selection screen, dahil napili na ang offers sa My Designs. Ipapakita pa rin ang selected-design summary at malinaw na completed na ang selection step. Ang pagbabago ng combination ay sa My Designs; hindi maghahalo ng unselected catalog offer at saved design references sa fixed saved-design mode.

Sa review, makikita ang bawat design, applicable entrance pricing mode, unit prices, subtotal, logistics, overtime, at final total. Walang automatic submission bago ma-review ang final quote.

## 6. Pricing at existing booking checks

```text
Entrance amount = entrance add-on price, kapag may package
Entrance amount = entrance solo price, kapag walang package

Items subtotal = package amount + applicable entrance amount + stand amount
Final total = items subtotal + booking logistics fee + booking overtime fee
```

Zero ang amount ng absent item. Ang fee rates, venue rules, overtime duration, caps, at availability ay kukunin sa existing policies, hindi hardcoded sa bagong UI.

Ang existing lower entrance add-on rate ang gagamitin; hindi magdadagdag ng isa pang percentage discount. Hindi rin ipagpapalagay na laging mas mababa ang configured add-on rate: ang actual catalog values ang source ng amounts.

Panatilihin at i-regression-test ang:

- Event date, admin-blocked dates, lead time, operating start window, duration, overnight handling, at conflict/temporary-hold checks.
- Complete venue address, map-pin requirement at existing map-unavailable fallback, logistics computation, at admin override behavior.
- Theme availability batay sa selected offers' Theme Decor inclusions; required palette at current limits; existing optional motto at notes.
- Sariling item quantities, required categories, at balloon color limits ng bawat canvas. Hindi pagsasamahin ang counts ng magkakaibang designs para pumasa ang isang incomplete design.
- Existing reference-photo count/size handling, AI reference handling, duplicate-submit protection, status, approval, deadlines, payment, at notifications para sa isang booking.

## 7. Server changes at consistency

- Bounded list of one to three IDs ang tatanggapin sa saved-design handoff at submission. Maaaring gamitin ang repeated existing `design_id` / `user_design_id` keys at `getlist()` para supported pa rin ang old single-ID links.
- I-reject ang malformed, duplicate, unknown, o foreign IDs at duplicate offer categories. Walang partial acceptance.
- I-load at i-revalidate ang lahat ng selected saved designs sa existing booking transaction; gamitin ang actual `DesignOffer.kind` at catalog relations.
- I-map ang package, entrance, at stand sa tamang selection state. Ang entrance na may kasamang package ay hindi lalagyan ng `(Solo)`.
- Server ang magbuo ng canonical offer summary at amounts. Hindi pagkakatiwalaan ang browser-supplied total, category, discount, o offer name.
- Magkaroon ng maliit na shared composition validator para sa resolved catalog selections. Gagamitin ito sa new booking submissions at sa create/edit/change paths kapag nagbabago ang selected catalog combination, para consistent ang one-per-category at stand dependency. Gagamitin ang existing pricing helpers para sa money at fee arithmetic.
- Panatilihin ang existing saved-price policy sa existing bookings at sa edit/change requests. Hindi kailangang baguhin o i-reprice ang historical booking para lang ma-view o ma-edit ang unrelated details. Ang legacy/custom records ay hindi i-reject dahil lang walang bagong structured metadata; strict validation applies sa bagong catalog combination, hindi sa historical unchanged selection.
- Kung magbago ang readiness o quote bago ang submission, ibabalik ang updated selection/quote para ma-review, at walang booking na ise-save gamit ang silently changed combination o total.
- Isang atomic booking operation ang gagawa ng booking at lahat ng submitted design references; kapag pumalya ang isa, walang partial booking. Pananatilihin ang existing transaction/locking at duplicate-submission guards. Ang newly written files na maiwan sa failed snapshot operation ay kailangang ma-clean up.

## 8. Storage at customer/admin display

Gamitin ang existing `Booking` -> many `Design` relationship at snapshot helper. Hindi kailangan ng bagong booking per design, permanent cart model, o mandatory schema migration sa proposal na ito.

Para sa bawat selected design, i-save ang independent canvas/image/upload snapshot kasama ang source design identity, category, offer identity/name, applied pricing mode, at component amount sa versioned `reference_snapshot` metadata. Ang authoritative booking total ay nasa `Booking`; huwag ipresenta ang buong booking total bilang presyo ng bawat component.

Sa customer details at admin references, lagyan ng malinaw na label ang bawat snapshot: Package, Entrance Arch, o Welcome Stand, kasama ang design/offer name. Gamitin ang existing gallery at image viewer. Existing legacy snapshots remain viewable kapag walang bagong metadata.

Kapag in-edit o dinelete ang original saved design, hindi magbabago ang submitted snapshot. Kapag binago ang booked offer combination sa existing edit/change process, panatilihin ang historical references at existing changed-package warning; hindi automatic papalitan ang submitted canvases.

Customer-submitted references at admin design deliveries/reviews ay mananatiling magkaibang existing features. Hindi papalitan ng feature na ito ang admin approval o design-review workflow.

## 9. Mga file/area na maaapektuhan

| Area | Proposed change |
| --- | --- |
| `app/templates/client/my_designs.html` | Typed selection actions, readiness wording, summary, at form handoff. |
| `static/js/my_designs.js` or a small companion module | One-per-category selection, stand dependency, price-mode updates, at account-scoped tab persistence. |
| Existing My Designs CSS | Responsive summary, disabled/selected/focus states, existing light/dark appearance. |
| `app/views/designs.py` | Card metadata at readiness/composition information needed by the selector. |
| `app/views/bookings.py` | Multi-ID GET/POST handling, canonical composition, quote review, at save-all snapshots. |
| `app/templates/client/booking/booking_page.html` | Typed saved-selection initialization, all previews, summary, Back/reset behavior, at submission payload. |
| Small shared selection helper + relevant create/edit/change callers | Composition validation without duplicating existing fee/pricing policy. |
| `app/design_reference_snapshot.py` | Typed, versioned component metadata at independent snapshots. |
| Customer/admin reference templates | Correct category/name labels, multi-design previews, at legacy fallback. |
| Relevant existing help/tour text | Update single-design booking instructions where necessary. |
| Relevant tests | Combination, pricing, validation, snapshots, navigation, at regression coverage. |

## 10. Verification at acceptance criteria

### Baseline verification already performed

Command:

```text
python manage.py test app.test_design_requirements app.test_booking_themes app.test_booking_form_parity app.test_booking_design_step --settings=Project.test_settings --noinput --verbosity 1
```

Result: 79 tests passed; Django system check reported no issues. Dalawang additional temporary diagnostic probes also ran successfully and established the current stand-only and last-ID-only behaviors described above. Hindi product fixes ang mga resultang ito. In-memory test database at temporary media storage ang ginamit; walang live booking na ginawa.

### Required checks kapag ini-implement na

1. Lahat ng six valid combinations sa rules table ay gumawa ng exactly one booking na may exactly one snapshot per selected design.
2. Empty, stand-only, repeated ID, more-than-three IDs, duplicate-category, foreign, deleted, unavailable, at incomplete designs ay blocked sa UI where applicable at sa direct POST. Walang partial booking/reference records.
3. Pareho ang displayed at saved prices para sa entrance solo/add-on, stand combinations, logistics, at overtime. Hindi dumodoble ang fees o discount.
4. Package removal/addition, entrance removal, at removal ng last base ay mag-update ng dependency at price nang tama. Walang stale zero-price/solo/add-on state.
5. Search, sorting, pagination, Back, form reopen/reset, at validation errors ay may predictable state; successful booking clears only the completed local selection.
6. Catalog/readiness changes before handoff/submission ay may reviewable feedback at hindi gumagawa ng silent partial/repriced booking.
7. Tampering sa total, names, kinds, at selection IDs ay hindi nakakapagpalit ng trusted quote o nakakalusot sa composition rules. Repeated clicks do not create extra bookings or extra snapshot sets.
8. Customer/admin show all typed references; snapshots survive edits/deletion of the editable source design; old snapshots remain readable.
9. Existing normal booking, old single-design URL, pending edit, later change requests, booked-price snapshots, payments, deadlines, notifications, at design-delivery/review behavior remain covered by targeted regression tests.
10. Browser verification sa desktop at mobile, light/dark, keyboard selection/focus, disabled-action explanations, readable prices/errors, at summary na hindi tumatakip sa controls.

Acceptance example: piliin ang Package 1-A design, Entrance Z design, at Stand Z design; makita ang package + entrance add-on + stand subtotal; dumaan sa existing event/preferences/review checks; makagawa ng isang booking na may tatlong malinaw na labeled snapshots at isang correct final total. Hindi makakapili ng pangalawang package design sa parehong booking.

## 11. Scope at next stage

Kasama ang multi-selection, pricing/dependency consistency, server validation, all-design snapshots, relevant display/help updates, at tests. Hindi kasama ang multi-event cart, quantity greater than one per category, merged canvas editor, bagong promo engine, o payment/status redesign.

Implementation choices left to the builder: exact CSS placement/breakpoints matching the existing UI, whether selection JS is added to the existing module or a companion file, and the smallest helper/module shape. Behavioral rules above are part of the proposal and should not be silently changed.

The proposal and interactive mockup were approved, and implementation is now recorded in `docs/superpowers/plans/2026-11-22-multi-design-booking.md`. See `docs/multi-design-booking-verification.md` for completed behavior, tests, independent review and the existing source-assertion limitations. The original proposal stage changed no application code or live booking data; implementation uses the existing schema.
