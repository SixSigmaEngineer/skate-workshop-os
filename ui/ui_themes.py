"""Skateboard theme catalog with optional vault-local image/palette overrides."""
import json
import re
from pathlib import Path

COLORS = ("bg", "panel", "ink", "muted", "line", "accent", "accent-2", "rail", "button-ink")
PALETTES = [
    ("default", "SKATE Original", "skate-logo-board.png", False,
     ("#ffffff", "#ffffff", "#1d2633", "#627186", "#dce4ed", "#2f67a5", "#435f8e", "#f8fafc", "#ffffff")),
    ("sol", "Sol", "sol.png", False,
     ("#fffaf1", "#fffdf8", "#392c20", "#75604b", "#e4d4b9", "#94521c", "#9e671b", "#f6ecd9", "#ffffff")),
    ("luna", "Luna", "luna.png", True,
     ("#131e29", "#1c2b3a", "#eef1e9", "#b3c0ca", "#405268", "#bad1e6", "#e0d1ae", "#172432", "#152536")),
    ("terra", "Terra", "terra.png", False,
     ("#f5f6ee", "#fffef8", "#24372e", "#5e7164", "#cbd7c8", "#366445", "#506c45", "#eaf0e3", "#ffffff")),
    ("devpost", "Deep Blue", "devpost.png", True,
     ("#081e2b", "#0e2b3b", "#e6f5fc", "#9bbdcc", "#305566", "#78d9f3", "#a3cde3", "#0b2533", "#092532")),
]


def catalog(folder: Path, fallback: Path) -> list[dict]:
    try:
        overrides = json.loads((folder / "themes.json").read_text(encoding="utf-8"))
        if not isinstance(overrides, dict):
            overrides = {}
    except (OSError, ValueError):
        overrides = {}
    result = []
    for key, label, filename, dark, values in PALETTES:
        colors = dict(zip(COLORS, values))
        override = overrides.get(key, {})
        if isinstance(override, dict):
            for name in COLORS:
                value = override.get(name)
                if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    colors[name] = value
        path = folder / filename
        if not path.is_file():
            path = fallback / filename
        version = str(path.stat().st_mtime_ns) if path.is_file() else "1"
        result.append({"id": key, "label": label, "filename": filename, "dark": dark,
                       "colors": colors, "image": f"/theme-boards/{filename}?v={version}",
                       "style": ";".join(f"--{name}:{value}" for name, value in colors.items())})
    return result
