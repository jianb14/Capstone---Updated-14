# Balloorina Floating Gallery preview

**Latest concept:** [Interactive balloons — preview 02](balloons/README.md),
available at **http://127.0.0.1:8765/balloons/**. The gallery experiment below is
preserved for comparison.

A standalone design preview with the current homepage copy, three existing event
images, and locally hosted Montserrat. No build step or external requests are needed.

From the repository root, run:

```powershell
.venv/Scripts/python.exe -m http.server 8765 --bind 127.0.0.1 --directory docs/hero-preview
```

Open **http://127.0.0.1:8765/**. Only the preview directory is served. Opening
`index.html` directly in a browser also works.

- Scroll down and back up to gather the floating photographs into a gallery row.
- **Our gallery** jumps to the completed composition.
- **Back to the beginning** returns to the start.
- The two hero CTAs show a preview message; they do not create bookings or load a
  package catalog. Without JavaScript, they link to equivalent inline messages.
- Sticky motion is enabled at widths of at least 1100px and heights of at least
  760px. Smaller viewports use normal scrolling with a subtle image lift.
- Reduced motion and JavaScript-disabled visits use a readable static layout.

## Assets and integration

The logo and three PNGs are unchanged copies from `static/images/`. Montserrat's
variable font and its OFL license are included in `assets/`.

The production Django homepage, routes, data, and shared styles are not connected
to this demo. Integration is a separate step after visual approval. The light
section below the hero demonstrates the transition to the rest of the page.

Desktop, completed-gallery, and mobile screenshots are stored in `screenshots/`.

## Verified in Chromium

- Nine viewport sizes, from 320 × 568 to 1920 × 1080, including short desktop
  windows and both sides of the sticky breakpoint.
- Eleven scroll positions per viewport: no horizontal overflow or intersections
  between photograph bounds and the actual headline, subtitle, or button text.
- Reverse scrolling, resizing while scrolled, and a reload at 50% progress with
  the same restored position and image transforms.
- Both CTA dialogs, Escape dismissal, keyboard focus restoration, and gallery
  navigation to the completed composition.
- Reduced-motion mode, live motion-preference changes, and JavaScript-disabled
  desktop/mobile layouts with functional fallback CTA messages.
- No JavaScript errors or external network requests during the browser checks.
