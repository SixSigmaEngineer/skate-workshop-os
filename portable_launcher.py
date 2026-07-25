"""SKATE packaged-build launcher (portable AND installed modes).

This entrypoint is used only for PyInstaller builds.

Modes, decided at startup:
  * INSTALLED  - an `installed.marker` file sits beside SKATE.exe. The vault
    lives in Documents\\SKATE, created and
    seeded on first run from the bundled `vault-seed` folder. Program Files
    stays read-only, as Windows expects.
  * PORTABLE   - no marker. SKATE runs from the folder beside SKATE.exe, so
    the vault, settings, and models travel together as one shareable folder.
"""

from __future__ import annotations

import os
import shutil
import sys
import traceback
from pathlib import Path


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


EXE_DIR = _exe_dir()
INSTALLED = (EXE_DIR / "installed.marker").exists()


def _documents_dir() -> Path:
    """Real Documents folder (handles OneDrive redirection) via the shell API,
    with a sane fallback."""
    try:
        import ctypes.wintypes

        CSIDL_PERSONAL = 5
        SHGFP_TYPE_CURRENT = 0
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
        if buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Documents"


def _seed_vault(root: Path) -> None:
    """Merge bundled demo content into the installed vault without deleting
    or replacing any user-created sessions, notes, settings, or files."""
    root.mkdir(parents=True, exist_ok=True)
    seed = EXE_DIR / "vault-seed"
    for sub in ("conversations", "sessions", "templates", "workshop-knowledge-documents"):
        target = root / sub
        source = seed / sub
        if source.exists():
            # Existing vaults may predate the bundled demo. Merge only the
            # missing demo files instead of skipping the entire folder.
            shutil.copytree(source, target, dirs_exist_ok=True, copy_function=_copy_if_missing)
        else:
            target.mkdir(parents=True, exist_ok=True)
    for fname in ("INDEX.md", "README.md"):
        if not (root / fname).exists() and (seed / fname).exists():
            shutil.copy2(seed / fname, root / fname)


def _copy_if_missing(source: str, destination: str) -> str:
    """copytree callback that preserves an existing destination file."""
    if not Path(destination).exists():
        shutil.copy2(source, destination)
    return destination


if INSTALLED:
    ROOT = _documents_dir() / "SKATE"
    _seed_vault(ROOT)
else:
    ROOT = EXE_DIR

os.environ["SKATE_ROOT"] = str(ROOT)
os.environ["PYTHONNOUSERSITE"] = "1"

_tools = EXE_DIR / "tools"
if _tools.exists():
    os.environ["PATH"] = f"{_tools}{os.pathsep}{os.environ.get('PATH', '')}"

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(EXE_DIR / "ui"))


LOG = ROOT / "skate-launch.log"


def _log(message: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass



def _alert(title: str, message: str) -> None:
    _log(f"{title}: {message}")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, f"SKATE - {title}", 0x40)
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


if __name__ == "__main__":
    try:
        _log(f"Launching SKATE ({'installed' if INSTALLED else 'portable'}) - vault: {ROOT}")
        import app  # noqa: E402

        app.main()
    except Exception:
        _log(traceback.format_exc())
        raise
