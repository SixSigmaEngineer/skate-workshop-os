# SKATE Stream Deck Neo icons

A hand-designed **SVG** icon set for SKATE and the Spotter voice agent.
Each key has a unique, meaningful glyph — no two keys look alike.

## Design system

- **Format:** SVG (vector). Stream Deck supports SVG directly, so the icons stay
  razor-sharp at any key size and need no regeneration step.
- **Look:** white glyph on a dark rounded square (`#16202C`), with a short label
  baked in at the bottom. Start/Stop talking use green/red accent labels so the
  mic state reads at a glance.
- **Brand:** `skate-mark.svg` and `spotter.svg` reproduce the SKATE logo (the
  A-frame on a skateboard) as clean vector art.

## The set (18 icons)

### Talk controls (Neo touch points)
- `start-talking.svg` — microphone (open mic)
- `stop-talking.svg` — muted microphone (close mic)

### Spotter stances (Neo keys)
- `prompt-observe.svg` — eye
- `prompt-find-waste.svg` — waste bin
- `prompt-five-whys.svg` — "5?"
- `prompt-hmw.svg` — lightbulb
- `prompt-process-map.svg` — flow nodes + arrow
- `prompt-frame-challenge.svg` — viewfinder
- `prompt-synthesize-notes.svg` — merging arrows
- `prompt-executive-readout.svg` — chart on a screen
- `prompt-kaizen.svg` — improvement cycle
- `prompt-next-experiment.svg` — flask
- `prompt-ask-spotter.svg` — question badge

### Navigation / brand
- `skate-mark.svg` — SKATE logo
- `spotter.svg` — SKATE logo with label
- `library-skateboard.svg` — skateboard
- `grind-rail.svg` — board on a rail
- `sessions-skate.svg` — stacked layers
- `start-skate.svg` — new note (+)

## Editing

These are plain SVG text files — open one and tweak the paths, colors, or labels
directly. To recolor the whole set, change the `#16202C` background or `#FFFFFF`
glyph fill. No build step or Python dependency is required.

See `HOTKEYS.md` for the full Stream Deck Neo key map and setup steps.
