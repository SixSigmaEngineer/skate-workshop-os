# Skateboard styles

Settings → Appearance previews five styles. Save Settings to keep the choice.

Replace a board image here with a PNG using the same filename:

- `skate-logo-board.png` — SKATE Original
- `sol.png` — Sol
- `luna.png` — Luna
- `terra.png` — Terra
- `devpost.png` — Deep Blue

Keep a wide, horizontal board image. The picker fits it without cropping.
Reload Settings after replacing an image. The app uses its modification time
to refresh the image. A missing image falls back to the bundled artwork.

Edit `themes.json` to change the matching style's colors. Use six-digit hex
colors (for example `#366445`). Invalid values use the original palette.
Images do not automatically recolor the app. `bg` is the page background,
`panel` is the surface color, `ink` is text, `muted` is secondary text, `line`
is borders, `accent` and `accent-2` are highlights, `rail` is the sidebar,
and `button-ink` is the text on primary buttons.

In a packaged installation, Settings → Open board folder creates this folder
in your active vault and copies any missing default boards. Existing boards
and palettes are preserved.
