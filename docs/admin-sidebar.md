# Admin sidebar

The shared admin layout uses a 260 px sidebar and an 80 px icon rail on desktop.
The panel button collapses/expands it locally without fetching or reloading the
page. The preference is saved as `balloorina-admin-sidebar` in localStorage and
applied before the sidebar is painted on a new admin page. Disabled browser
storage does not prevent toggling. Navigation links keep normal page navigation.

Collapsed items keep their accessible names and expose hover/keyboard tooltips.
Pending counts become small indicator dots; the tooltip includes the current
count and updates when the notification controller changes that count. Tooltips
use a popover to avoid clipping by the scrollable navigation container. Escape
dismisses a tooltip. Reduced-motion preferences disable the width animation.

At 1024 px and below, the sidebar becomes a full-label drawer opened from the
existing hamburger button. Offscreen navigation is inert. The drawer supports
focus containment, Escape, its close button and backdrop dismissal, restores
focus to the trigger, and releases its scroll lock when the viewport returns to
desktop. Opening the mobile menu does not overwrite the desktop preference.

`admin_sidebar.css` is scoped to the shared admin shell. Existing navigation URLs,
server active states, role checks and live count hooks are preserved. Detail/editor
paths select the longest matching sidebar link. The header avatar, notifications
and theme controls retain their existing behavior.

The opt-in `app.test_admin_sidebar_browser.AdminSidebarBrowserTests` suite verifies
collapse without document requests, icon names/tooltips, live counts, preference
persistence, keyboard controls, blocked storage, light/dark appearance, mobile
focus/backdrop/Escape handling and resize behavior with Chrome/Playwright. Set
`RUN_ADMIN_SIDEBAR_BROWSER=1` and use an isolated PostgreSQL test database.
