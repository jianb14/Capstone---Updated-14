# Master Design Guide — Lineal Color Icon Style

This document defines the EXACT visual style that ALL assets must follow in the event designer drag-and-drop system.
Every SVG (balloons, furniture, decorations, frames, party items, themes, text signs) must strictly use this style.

---

## Style Name: Lineal Color Icon

1. **Bold Black Outline**: Every shape must have a thick black stroke border (`stroke="#222"`, `stroke-width="1"`).
2. **Flat Solid Color Fill**: The interior fill is ONE flat solid color. NO gradients, NO metallic sheen, NO glassmorphism. Just pure clean flat color.
3. **No Highlights**: No white reflection dots or specular highlights. Pure flat color.
4. **No Outline Glow / No Drop Shadow**: No blur filters, no glow effects. The bold black outline IS the visual anchor.
5. **Clean, Minimal Design**: Objects must look like clean, professional icons. Think of the style used by Flaticon "Lineal Color" packs.
6. **Isolated Object**: Every asset is a standalone object with a transparent background. No accessories unless they are part of the object itself (e.g., a cake has layers, a chair has legs).

---

## Balloon Specific Rules

- Shape: Pure circle (ellipse), heart, star, number, or letter.
- **NO string, NO stick, NO knot, NO tie**. The balloon is just the shape itself, floating.
- Bold black outline wraps the entire balloon shape.

---

## Color Palette

All assets should use these exact colors when applicable:

| Color Name | Hex Code   |
|------------|------------|
| Red        | `#e63946`  |
| Blue       | `#4895ef`  |
| Yellow     | `#fee440`  |
| Green      | `#06d6a0`  |
| Pink       | `#ffb3c6`  |
| Purple     | `#9d4edd`  |
| Orange     | `#f77f00`  |
| Gold       | `#ffb703`  |
| Silver     | `#ced4da`  |
| White      | `#f8f9fa`  |
| Black      | `#212529`  |
| Brown      | `#8b5a2b`  |
| Cream      | `#faf0e6`  |
| Sage       | `#a7c4a0`  |

---

## SVG Construction Template

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}px" height="{H}px">
  <!-- Main shape with bold outline and flat fill -->
  <{shape} fill="{COLOR}" stroke="#222" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```


## Summary

If an AI or human reads this guide, they should produce assets that:
- Look like professional "Lineal Color" icon pack items
- Have bold black outlines
- Have flat solid color fills
- Have NO gradients, NO shadows, NO glow effects
- Are isolated floating objects on transparent backgrounds
