# Spotlight feature tour

The guide introduces the main parts of Booking, Design Canvas and Payments. It is a read-only feature tour with Next and Back, a highlighted region, and a darkened background. It does not guide form completion, require answers, or advance in response to validation.

## Open and navigate

- Booking: Guide in the calendar header or booking form; My Bookings has its own overview and details tours.
- Canvas: Guide beside Save on desktop; Tools > Guide on phones/tablets.
- Payments: Guide in My Payments, the payment page and supported details windows.

Guide starts the tour. Next advances to the next explanation, Back returns to the previous one, and Done closes the final step. Close or Escape ends the tour at any point. The tour never starts automatically and does not remember an ON state.

## Spotlight and interaction

The current region stays at its original brightness inside a rounded focus box. The rest of the page is darkened. The explanation shows the region's purpose and the current step number.

Guide launchers outside modals have a quiet border and solid neutral surface, including the calendar, account-page headers, desktop Canvas toolbar and payment page. The calendar button matches the adjacent legend's height and vertical alignment. Only launchers inside modals use compact padding, no border and a transparent resting background with ghost hover. Both treatments retain subtle hover feedback and visible keyboard focus. Their shared background variable prevents contextual styles from suppressing feedback.

Enhanced dialog headers center Guide and Close/Done on the same line. Booking forms use one shared size for Guide and X: 36px for mouse pointers and 44px for coarse pointers. Payment-details controls clear inherited vertical offsets, and the payment-page Guide aligns with the Secured badge. Calendar and payment headers group their actions; booking forms reserve a separate row above the section indicator. Narrow dialog headers wrap their controls so titles and supporting text have enough width.

### Complete launcher list

| Area | Where to find Guide |
| --- | --- |
| Booking | Events Calendar header; booking form above the section indicator |
| My Bookings | Page header; Booking Details; Edit Booking/Request Changes; Your Event Design |
| Design Canvas | Desktop toolbar beside Save; Save Design window |
| Design Canvas on mobile | Tools; Assets/Text/Uploads/Layers panel; Design Checklist |
| Payments | My Payments header; Payment Details window; booking payment page; booking-change payment page |

Dialog launchers appear inside their supported windows. Available booking actions depend on the reservation status. Canvas inventory categories share one mobile panel, and both payment flows share the same payment-page template.

Opening and closing use brief fades. Next/Back moves the spotlight and panel with a short transition and fades the new explanation into place. Scroll and resize tracking follows the target immediately. Reduced-motion preferences turn off these effects. Rapid navigation, closing during an animation and leaving a page cancel pending motion safely.

While the tour is open, only its controls are interactive. Application clicks and document keyboard shortcuts cannot submit a booking, delete a canvas item, save a design or start checkout. Tab stays in the tour. Existing form answers are preserved, and Escape closes the tour without closing an underlying booking or native dialog.

The tour describes the visible interface only. Hidden or unavailable regions are skipped. Offscreen targets scroll into view, and spotlight bounds follow viewport and scroll-container clipping. Leaving an account page, removing the current target or changing its modal context closes the tour safely.

In create/edit booking forms, the schedule spotlight groups Start and End together. The venue spotlight covers the complete location section, including the address, map and location controls. Design Preferences has separate explanations for Theme / Decor Style, Color palette, Motto / Backdrop text, Special requests and Reference pictures; each highlights its full field group, including labels and related controls. These steps appear when that form section is visible. Large sections remain clipped to the visible modal/viewport area on small screens.

Public/authentication/profile/reviews/concerns pages have no guide. The AI assistant retains its existing design guide. The previous task-aware coaching, hover settings and canvas evaluation/save hooks were removed.

## Implementation

- `static/js/site_guide_content.js`: static explanations and visible target selection.
- `static/js/site_guide.js`: native modal lifecycle, Next/Back, spotlight geometry, keyboard containment and cleanup.
- `static/css/site_guide.css` and shared templates: dimming mask, focus outline and compact tour panel.

No dependency, database change, backend endpoint or AI/payment request was added.

## Verification

```powershell
$env:RUN_SITE_GUIDE_BROWSER='1'
$env:RUN_ACCOUNT_MENU_BROWSER='1'
.\.venv\Scripts\python.exe manage.py test app.test_site_guide_browser app.test_account_menu_browser --settings=Project.test_settings
```

Screenshots and raw logs are in `.booking-followup-check/site-guide/spotlight/` and `.booking-followup-check/site-guide/`. See [verification results](site-guide-verification.md) for test counts and the existing complete-suite failures.
