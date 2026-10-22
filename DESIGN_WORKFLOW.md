# Offers, inclusions, and design requirements

The designer now supports Package, Entrance Arch, and Welcome Stand. Each saved design uses one offer. Offer names, inclusions, preview images, and prices remain in the existing catalog; Entrance designs use the solo price.

## Admin setup

1. Open **Canvas Asset Management** and select the appropriate tab.
2. Set **Available for** on a category, then its assets. Sharing an image with several tabs uses the same asset record.
3. Move the relevant assets into precise counting categories. Migrations create **Panels**, **Arch Frames**, and **Stand Frames** without guessing which existing images belong in each. Existing images initially remain available to Package. **Styrofoam Name** is a built-in text preset with a protected counting category, available to all three offer types. Its existing asset/category IDs are retained. Admin cannot edit, hide, or delete the preset or its category; manage inclusion and quantity in the offer editor. The canvas shows a separate name button outside category accordions only when the selected offer includes that category. The preset is stored in the shared database and does not depend on browser/device storage.
4. On balloon categories, select **Balloon category**. The flag identifies color-controlled assets even after a category is renamed. A category's **Available for** choices determine which offer editors can select it.
5. Create or edit the Package, Entrance, or Stand in catalog management. Use the single **Inclusions** editor:
   - **Add Item** selects a canvas category; each category can appear once. Enter a separate item name and optional quantity. Fixed quantity sets the canvas maximum; a blank quantity means **Included**, with no numeric maximum.
   - **Required** defaults to the full quantity (or 1 for unlimited items). Expand **Design settings** to change its minimum or category. The minimum cannot exceed a fixed quantity. Optional items have a minimum of zero.
   - **Add Service** creates a text-only inclusion such as setup or delivery. Services appear in customer details and never count toward design completion.
6. **Balloon settings** appears only when a balloon category is included. Its color limit is shared by all balloon categories in the offer and appears automatically in the customer preview.
7. Browse or drop preview images. The limit is **2 images total**, including retained images. Remove/replace choices are applied only when saving. Field errors retain entered rows and selected files in the editor.
8. Under **Visibility**, enable **Available in Create Design** when ready. Every included canvas category needs an active applicable asset, and the offer needs at least one required category. Entrance also needs a solo price. The live customer preview updates while editing; Save applies details, inclusions, and generated rules together.

Offers start disabled until these rules are configured. Existing bookings and their saved quotes are preserved. Hiding or removing an asset can make an offer temporarily unavailable until its asset configuration is repaired.

The structured `OfferInclusion` list is the source for both catalog `features` and `DesignRequirement` records. Do not maintain a second requirements list. The import migration splits only clear leading quantities, preserves dimensions and notes, and prioritizes existing configured minimums, maximums, and color limits. Unmatched inclusion rows show **Needs review**: select a category in Design settings or change the row to Service before saving. Migration does not automatically enable offers.

## Customer behavior

Both Create Design entry points offer the three tabs and show inclusions and required quantities before opening the editor. Green progress with a checkmark means the required minimum is met; the included allowance is displayed separately. Optional items do not prevent booking.

Incomplete designs can be saved as drafts. My Designs shows what is missing and offers Continue Editing. Book Now appears only for eligible designs. Eligibility is checked again at the booking URL and final submission, before a booking record is created.

In **Admin → Site Settings → Design Settings**, set **Maximum saved designs per customer** (default: 20). Draft and Ready to book designs both count. My Designs shows the total allowance regardless of search or pagination. At or above the limit, customers can edit existing designs, delete unused designs, and book eligible designs; new designs cannot be saved until space is available. Lowering the allowance preserves existing designs. New saves lock the customer row and recheck the current setting inside the creation transaction, so concurrent PostgreSQL requests cannot take the same last slot. A stale-tab save conflict returns HTTP 409 without clearing the canvas or local draft.

Uploaded images and backgrounds are references. They never fulfill required categories, even if they depict balloons or panels. Each official catalog placement counts as one design element, including SVGs with multiple paths. Blank catalog text does not fulfill a requirement.

Legacy images are recognized only when their source uniquely identifies an eligible catalog asset. Items that cannot be identified remain editable and must be re-added from the catalog to count.

## Verification

Run the relevant tests against the isolated SQLite configuration:

```powershell
.\.venv\Scripts\python.exe manage.py test app.test_offer_editor app.test_design_requirements app.test_design_save app.test_select_design_confirm app.test_design_limits app.test_design_canvas_ui app.test_booking_design_step --settings=Project.test_settings --noinput
node static/js/design_rules.test.cjs
```

Optional browser tests use Playwright and installed Microsoft Edge. They cover all six offer forms in both themes at desktop, tablet, and mobile sizes; inclusion editing; browsing and dropping uploads; validation recovery; and customer canvas save/reopen and undo/redo:

```powershell
$env:RUN_DESIGN_BROWSER = '1'
.\.venv\Scripts\python.exe manage.py test app.test_offer_editor_browser app.test_design_browser app.test_design_limits_browser --settings=Project.test_settings --noinput
```

`Project.test_settings` uses an in-memory SQLite database, local temporary media, and in-memory email. It does not reuse the PostgreSQL test database configured by the regular settings.
The concurrent last-slot test requires a database supporting row locks and is skipped on SQLite.
