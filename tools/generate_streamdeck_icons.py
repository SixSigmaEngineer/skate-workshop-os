"""
Stream Deck Neo icons are now a hand-designed SVG set.

The previous Pillow-based PNG generator has been retired. The icon set lives in
`SKATE/streamdeck-neo-icons/` as editable .svg files (Stream Deck supports SVG
directly), so there is no build step.

To change an icon, edit its .svg by hand. To restyle the whole set, change the
shared background color (#16202C) or glyph fill (#FFFFFF) across the files.

See `SKATE/streamdeck-neo-icons/README.md` for the full list and design notes.
"""

import sys


def main() -> None:
    print(__doc__.strip())
    print("\nNothing to generate — edit the .svg files directly.")


if __name__ == "__main__":
    sys.exit(main())
