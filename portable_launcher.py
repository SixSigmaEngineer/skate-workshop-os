"""SKATE packaged-build launcher (portable AND installed modes).

This entrypoint is used only for PyInstaller builds.

Modes, decided at startup:
  * INSTALLED  - an `installed.marker` file sits beside SKATE.exe. The vault
    lives in Documents\\SKATE, created and
    seeded on first run from the bundled `vault-seed` folder. Program Files
    stays read-only, as Windows expects.
  * PORTABLE   - no marker. SKATE runs from the folder beside SKATE.exe, so
    the vault, settings, and models travel together as one shareable folder.

Vault location is *validated* before use. Windows will happily report a
Documents folder that does not exist on disk - most commonly when OneDrive
Known Folder Move is configured but OneDrive is signed out, unlinked, or has
not yet materialised the folder. Trusting that answer used to crash the app
on startup, so each candidate is now probed and the first usable one wins.
"""

from __future__ import annotations

import os
import json
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

# Startup happens before the log file's location is known, so early messages
# are buffered here and flushed once ROOT has been resolved.
_STARTUP_NOTES: list[str] = []


def _note(message: str) -> None:
    _STARTUP_NOTES.append(message)


def _is_writable(path: Path) -> bool:
    """True only if we can actually create a file inside `path` right now."""
    probe = path / ".skate-write-test"
    try:
        probe.touch()
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def _shell_documents_dir() -> Path | None:
    """What Windows *says* the Documents folder is. May not exist on disk."""
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
    return None


def _local_appdata() -> Path | None:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else None


def _vault_root() -> Path:
    """Pick the first Documents-like folder that genuinely works.

    Existing installs are unaffected: a Documents folder that is present and
    writable is still chosen first, so no vault ever moves on upgrade.
    """
    home = Path.home()

    # (parent folder, may we create it if missing?)
    candidates: list[tuple[Path, bool]] = []
    shell = _shell_documents_dir()
    if shell is not None:
        # Never create this one. If it is a OneDrive path that OneDrive has
        # not materialised, making it ourselves starts a fight with sync.
        candidates.append((shell, False))
    candidates.append((home / "OneDrive" / "Documents", False))
    candidates.append((home / "Documents", True))
    local = _local_appdata()
    if local is not None:
        candidates.append((local, True))
    candidates.append((home, False))

    seen: set[Path] = set()
    for parent, may_create in candidates:
        if parent in seen:
            continue
        seen.add(parent)
        try:
            if not parent.is_dir():
                if not may_create:
                    _note(f"vault candidate skipped (missing): {parent}")
                    continue
                parent.mkdir(parents=True, exist_ok=True)
            if not _is_writable(parent):
                _note(f"vault candidate skipped (not writable): {parent}")
                continue
            root = parent / "SKATE"
            root.mkdir(parents=True, exist_ok=True)
            return root
        except OSError as exc:
            _note(f"vault candidate skipped ({exc.__class__.__name__}): {parent}")
            continue

    # Everything above failed. Run beside the executable rather than not at all.
    _note("no usable Documents folder found - falling back to the SKATE.exe folder")
    return EXE_DIR


def _seed_vault(root: Path) -> None:
    """Merge bundled demo content into the installed vault without deleting
    or replacing any user-created sessions, notes, settings, or files."""
    root.mkdir(parents=True, exist_ok=True)
    seed = EXE_DIR / "vault-seed"
    removed = set()
    for manifest_path in (root / ".trash").glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("state") in {"pending", "trashed"}:
                removed.update(path for path in manifest.get("paths", []) if isinstance(path, str))
        except (OSError, ValueError, TypeError, AttributeError):
            continue

    def copy_seed_file(source: str, destination: str) -> str:
        # A removed demo note must not reappear when the installed app restarts
        # or updates. Restoring it through Trash makes it available again.
        if Path(destination).relative_to(root).as_posix() in removed:
            return destination
        return _copy_if_missing(source, destination)

    for sub in ("conversations", "sessions", "templates", "workshop-knowledge-documents", "models", "theme-boards"):
        target = root / sub
        source = seed / sub
        if source.exists():
            # Existing vaults may predate the bundled demo. Merge only the
            # missing demo files instead of skipping the entire folder.
            shutil.copytree(source, target, dirs_exist_ok=True, copy_function=copy_seed_file)
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
    # A vault problem must never stop SKATE from starting. Worst case we run
    # out of the executable's own folder, exactly like portable mode.
    try:
        ROOT = _vault_root()
    except Exception:
        _note("vault location failed unexpectedly:\n" + traceback.format_exc())
        ROOT = EXE_DIR
    try:
        _seed_vault(ROOT)
    except Exception:
        _note(f"vault seeding failed for {ROOT}:\n" + traceback.format_exc())
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


def _flush_startup_notes() -> None:
    while _STARTUP_NOTES:
        _log(_STARTUP_NOTES.pop(0))


def _alert(title: str, message: str) -> None:
    _log(f"{title}: {message}")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, f"SKATE - {title}", 0x40)
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


if __name__ == "__main__":
    try:
        _flush_startup_notes()
        _log(f"Launching SKATE ({'installed' if INSTALLED else 'portable'}) - vault: {ROOT}")
        import app  # noqa: E402

        app.main()
    except Exception:
        _log(traceback.format_exc())
        raise
