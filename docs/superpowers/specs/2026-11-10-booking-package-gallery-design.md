# Package gallery in the booking modal

Approved: the user accepted replacing the inline preview with the proposed gallery view.

Keep Event Details → Select Package → Design Preferences → Review & Confirm. Clicking a package card only selects the package. View sample setups temporarily replaces the package list inside the same modal with an image gallery, package name, current price and inclusions. The gallery uses a fixed image area and a bounded inclusions list, so images do not lengthen the form. Desktop uses two columns; mobile stacks the same content.

Back to packages restores the list at its previous scroll position and focus without changing the selection. Previous/Next image and keyboard arrows navigate the existing maximum of two images. Escape returns to the list. Select this package uses existing selection/pricing handlers and returns after selection succeeds. Cancelling a paid change warning leaves the prior selection and gallery intact. Extras use the same preview view and retain their selection rules. Missing/broken images show existing fallback feedback.

Use shared JavaScript/CSS for create/edit. No nested dialog, new step, dependency or backend policy change. Keep the existing Remove package control and saved-design handling. Bump asset versions.

Latest preview affordance refinement approved by the user: keep View sample setups compact on the left and Remove package on the right in the same footer. Both use the same small text size, with reduced vertical spacing. The preview retains its image icon, chevron and keyboard focus outline, but does not stretch across the card or show a full-width hover fill. Retain native button semantics and the existing English labels.

Date/start-time prerequisite hints use the existing theme-muted color at full opacity, sentence case and readable helper-text sizing. These are guidance, so they do not use validation-error red. Apply the same presentation to create and edit forms.

Verify list height is unchanged by selection; viewing samples does not select; scrolling/focus and keyboard work; gallery selection respects async price warnings; long inclusions and portrait/landscape images fit phone/desktop in both themes.
