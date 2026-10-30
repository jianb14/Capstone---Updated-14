# Canvas fonts

The text menu contains Poppins, Montserrat, Cursive Sans, Cursive Serif,
Bebas Neue, Liberation Sans, Histore Magica, Angelic Pearl, Megalona,
Day Roman, Sanchez, Ananda, Jane Austen, Michland, Golden Hills,
Impact, Steelfish, and Bebas Kai, in that order.

Saved lettering can keep its previous family. Selecting it does not put removed
fonts back in the menu. Birthday and script presets use Cursive Serif and
Cursive Sans.

## Bundled families

The following nine families have actual font files in `static/fonts/canvas/`:

- Poppins and Montserrat: Google Fonts, SIL Open Font License.
- Cursive Sans and Cursive Serif: Wojciech Kalinowski through Font Library,
  SIL Open Font License.
- Bebas Neue and Sanchez: Google Fonts, SIL Open Font License.
- Liberation Sans: the upstream Liberation Fonts 2.1.5 release, SIL Open Font License.
- Day Roman: Apostrophic Labs' original free distribution, with its `DAY-O.txt`.
- Bebas Kai: Dharma Type's upstream webfont, SIL Open Font License.

The original license/copyright information is retained alongside the assets.
`static/fonts/canvas/sources.json` records source URLs, original SHA-256 hashes,
and delivered file hashes. WOFF2 conversion changes the font container while
preserving the original names and glyphs. Day Roman is delivered as its original TTF.

## Families that still need webfont files

No webfont package was supplied for Histore Magica, Angelic Pearl, Megalona,
Ananda, Jane Austen, Michland, Golden Hills, Impact, or Steelfish.
The user confirmed the spelling **Ananda**.

These entries try the exact installed family through CSS `local()`. They are
disabled on devices without that family; another typeface is never silently
applied under their names. Impact is usually installed on Windows but still needs
a webfont package for reliable use on other devices.

To activate a family on every device, add its webfont package to
`static/fonts/canvas/<family>/`, preserve its accompanying license, and add the
file's URL to that family's `@font-face` rule in `static/css/canvas_fonts.css`.
The files need to cover the website and its customer text-design workflow.
The loader will automatically enable the menu entry after successfully loading
the real font face. Update the stylesheet/script version in the template when
releasing new files.

## Verification

The browser test in `app/test_canvas_interactions_browser.py` checks the exact
menu, real font loading with Google Fonts blocked, selection/rendering in mobile
and desktop layouts, unavailable fonts, and legacy-font selection.
