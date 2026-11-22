# Theme Decor catalog images

The user approved adding admin Theme Decor images alongside customer uploads,
using the same behavior as Panels and Balloons.

## Approach

Reuse the existing Canvas Asset admin and signed catalog placement flow. Remove
the Theme Decor-only restrictions in the asset form, model save signal, and
eligible catalog query. A separate admin page or asset type would duplicate the
existing workflow without improving this request.

## Behavior and constraints

- Admins can add, edit, hide, and delete ordinary images in Theme Decor using
  Canvas Assets. The built-in category itself remains protected.
- Active admin images appear above the existing category upload controls.
- Catalog and uploaded images share the same Theme Decor category allowance.
- Theme Decor remains hidden and unusable when excluded from the selected offer.
- Customer uploads still work when the category has no admin images.
- Preserve Styrofoam Name protection, owner-private uploads, offer readiness,
  background removal, and existing catalog validation and availability rules.
- No new model fields, migrations, dependencies, default images, or page layout.

## Verification

Exercise admin CRUD and authorization, availability and hidden assets, mixed
catalog/upload counting and maximum enforcement, saved-design reopening, and
included/excluded Theme Decor in the browser. Run related catalog/upload/booking
regressions and Django checks.
