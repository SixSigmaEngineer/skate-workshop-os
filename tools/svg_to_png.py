"""
Convert the Stream Deck Neo SVG icons to PNG.

Usage (from the SKATE folder):
    python tools/svg_to_png.py

Outputs <name>.png next to each <name>.svg in streamdeck-neo-icons/ at 288x288
(crisp for Stream Deck Neo keys).

Needs one of these renderers (the script tries them in order):
    pip install cairosvg          # best fidelity
    pip install svglib reportlab  # pure-Python fallback, installs cleanly on Windows
"""

from __future__ import annotations

import sys
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[1] / "streamdeck-neo-icons"
SIZE = 288


def convert_with_cairosvg(svgs: list[Path]) -> bool:
    try:
        import cairosvg  # type: ignore
    except Exception:
        return False
    for svg in svgs:
        cairosvg.svg2png(
            url=str(svg),
            write_to=str(svg.with_suffix(".png")),
            output_width=SIZE,
            output_height=SIZE,
        )
        print(f"  {svg.stem}.png")
    return True


def convert_with_svglib(svgs: list[Path]) -> bool:
    try:
        from svglib.svglib import svg2rlg  # type: ignore
        from reportlab.graphics import renderPM  # type: ignore
    except Exception:
        return False
    for svg in svgs:
        drawing = svg2rlg(str(svg))
        if drawing is None:
            print(f"  ! could not parse {svg.name}")
            continue
        scale = SIZE / drawing.width if drawing.width else 1
        drawing.width = drawing.height = SIZE
        drawing.scale(scale, scale)
        renderPM.drawToFile(drawing, str(svg.with_suffix(".png")), fmt="PNG")
        print(f"  {svg.stem}.png")
    return True


def main() -> int:
    svgs = sorted(ICON_DIR.glob("*.svg"))
    if not svgs:
        print(f"No .svg files found in {ICON_DIR}")
        return 1

    print(f"Converting {len(svgs)} icons to {SIZE}x{SIZE} PNG...")
    if convert_with_cairosvg(svgs):
        print("Done (cairosvg).")
        return 0
    if convert_with_svglib(svgs):
        print("Done (svglib).")
        return 0

    print(
        "\nNo SVG renderer installed. Install one of:\n"
        "    pip install cairosvg\n"
        "    pip install svglib reportlab\n"
        "then run this script again."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
