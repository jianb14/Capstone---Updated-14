# Shared customer booking form components

Create Booking and My Bookings Edit / Request Changes share
`static/css/booking_form_components.css` and `static/js/booking_form_ui.js`.
These are scoped to the two wizard roots, leaving admin and read-only booking
details alone. Both templates load the same components after their legacy CSS.

The five-column stepper uses a 10% left offset and 20% progress increments.
Labels wrap within their own columns. The review uses two cards on desktop and
one column below 780px, with wrapping addresses/notes and image thumbnails.

`BookingFormUI.renderPreview` receives selected item labels and image arrays.
It always renders a labelled card for every selected item, including an empty
state for missing/broken previews. It keeps the existing maximum of two previews
per item. Create IDs and edit item names are normalized at their call sites.

Form icons are rendered as native outline SVGs, including dynamically inserted
review rows. They do not depend on paid/unavailable Font Awesome glyphs.

Shared template partials in `client/booking/`:

- `_reference_upload.html`: file selection and drag/drop using existing UI and
  submission inputs. Existing accumulation/removal logic still enforces four
  total reference images, including saved edit images. File types/limits and
  server validation are unchanged.
- `_palette_custom.html`: custom color control using existing picker IDs and
  palette handlers. Selected chips/rings use the site's neutral colors.
- `_map_sources.html`: compact visible OSM/geoBoundaries links with expandable
  detailed boundary credits. Tile-provider attribution stays visible on the map.

Step 3's included-duration explanation is in English on both forms. The fee and
availability calculations are unchanged. Review text is escaped before HTML
insertion so long/custom addresses, event names and notes remain plain text.

Both themes use neutral grayscale surfaces and selection states. Package cards
use a centered 30px selection circle with an SVG mask check, without icon-font
dependencies. The Other theme chip uses the shared outline pencil icon.
`AppToast` presents a single message when callers provide a title and text;
confirmation dialogs keep their separate title and explanation.
