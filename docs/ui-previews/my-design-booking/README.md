# My Designs booking selection — interactive UI proposal

Throwaway preview for visual/interaction approval. Not connected to application routes, the database, payments, or booking submission.

Open `index.html`, or use the brainstorming companion URL provided in chat. All mockup assets are local. Prototype controls live in the thin preview toolbar above the product navigation.

Design question: Which saved package, entrance, and welcome stand will belong to this one booking?

Direction: framed-sheet composition; preserve Balloorina's Montserrat, black/white controls, logo, top navigation, and saved-design cards. The existing shell takes precedence over a new L-frame/sidebar. No redesign of the product navigation. Direction draw metadata is in `.booking-followup-check/my-design-selection-preview/taste`.

Face/signature: actual Balloorina wordmark and three typed design slots, with live entrance solo/add-on pricing. The largest product amount is the selected designs subtotal. The illustrations are code-drawn sample canvas compositions, not submitted customer designs.

Dataset/jobs:
- Customer works with saved designs, not quantities or separate event bookings.
- Six sample designs: two packages, two entrances, two stands.
- Package 1-A 4,799 and Package 1-B 5,799 mirror names/prices in the supplied screenshot.
- Entrance Z sample rates: solo 2,500; with-package 1,500.
- Entrance X sample rates: solo 3,000; with-package 1,800.
- Stand Z sample rate 1,200; Stand A sample rate 1,000.
- Illustrative design names and entrance/stand rates require real catalog data in implementation.
- Main job: select/remove one per kind; continue only with a package or solo entrance.
- Removing the last base clears the dependent stand with visible feedback.
- Cards remain editable; the prototype Edit action only explains its destination.
- Search/type filters/sort preserve selection.
- Desktop: three card columns plus a 320px selection summary. At 1440: content width 1296 = 952px library + 24px gap + 320px summary; library grid is 3 x 306.67px + 2 x 16px.
- Tablet/phone: summary becomes an explicit bottom sheet opened from a compact fixed bar; content bottom padding keeps the final controls reachable.

States to review: empty, one base, all three, solo entrance plus stand, locked second-category choices, no search results, and mobile summary. Use Start empty / Show full selection and the theme toggle.

No real booking is created by Continue to Booking; its preview dialog explains the existing Event Details destination. Approval of this mockup does not automatically implement the feature.

## Verification and visual review

Framed-sheet draw seed: 885982615. Kept the existing brand and navigation instead of introducing the dealt L-frame shell.

Browser interaction checks passed for all three categories, duplicate-category locks, solo/add-on arithmetic, removing the last base, search retention, handoff preview, theme switch, mobile sheet, Escape/focus return, no horizontal overflow at 320/390/768/1024/1440px, and no page or asset errors. Source lint: 0 failures, 0 warnings. Final rendered inspection at 1440/768/390px: 0 failures, 0 warnings.

Visual review: inspected desktop, tablet, and phone renders. Balloorina branding stays visible; selected cards align; the subtotal is computed from the shown component prices; the desktop rail and phone sheet carry the same three categories; no fees or final total are invented. The mobile sheet keeps the continue action clear. The sample drawings intentionally occupy saved canvas previews. No extra charts or unrelated dashboard blocks were added.

Saved screenshots: `desktop-preview.png`, `mobile-preview.png`, and `mobile-summary.png`. Product behavior has not been implemented or verified against live application data.
