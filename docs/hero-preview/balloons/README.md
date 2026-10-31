# Interactive balloon hero — preview 02

Open **http://127.0.0.1:8765/balloons/** with the existing preview server running.
From the repository root, the server can be started with:

```powershell
.venv/Scripts/python.exe -m http.server 8765 --bind 127.0.0.1 --directory docs/hero-preview
```

This standalone preview refines the original Balloorina hero. It keeps the logo,
homepage wording, monochrome palette, and existing balloon/party illustrations.
The original Floating Gallery experiment remains available at the server root.

## Try it

- Move the mouse across the hero for layered parallax; approach a balloon to
  gently push it away, then move away to see it spring back.
- Hover over each CTA for its arrow and background response.
- Scroll down and back up for the balloon exit and next-section reveals.
- Use the sun/moon button to compare light and dark themes.
- Use **Pause motion** at the bottom right of the hero to stop the animation.
- Use the browser's responsive mode for the mobile arrangement. Touch scrolling
  stays native; pointer repulsion is for fine mouse input only.

There is no sticky scroll sequence or animation library. The animation pauses
when the hero is offscreen or the document is hidden. Reduced motion disables
animation; without JavaScript, the page has a readable static composition.

The CTAs and feature navigation show preview messages rather than connecting to
booking, accounts, or package data. The local font and assets are shared with the
parent preview directory. No production templates, scripts, routes, or data are
changed. Integration into the homepage follows visual approval.

## Browser verification

Checked in Chromium at nine viewport sizes, from 320 × 568 to 1920 × 1080:

- No horizontal overflow or decoration/text collisions at four scroll positions
  and when approaching either main balloon with the cursor.
- Pointer repulsion, pause/resume, native scrolling, and reloading mid-scroll.
- Animation stops outside the hero and when reduced motion is enabled.
- Theme switching and theme persistence, both CTA dialogs, Escape dismissal,
  and focus restoration.
- Touch layout and four JavaScript-disabled layouts with working CTA fallbacks.
- No JavaScript errors or external network requests.

Screenshots: `screenshots/desktop.png`, `screenshots/mobile.png`,
`screenshots/light.png`, and `screenshots/scroll.png`.
