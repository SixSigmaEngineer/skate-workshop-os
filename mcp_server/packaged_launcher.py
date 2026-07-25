"""PyInstaller entry point for the standalone SKATE MCP server.

The desktop app and MCP companion must resolve the same vault. Installed
builds use the SKATE folder under Documents; portable builds use the folder
beside the EXE.
"""

from __future__ import annotations

import os
import sys
import multiprocessing
from pathlib import Path


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _documents_dir() -> Path:
    try:
        import ctypes
        import ctypes.wintypes

        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
        if buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Documents"


EXE_DIR = _exe_dir()
INSTALLED = (EXE_DIR / "installed.marker").exists()
ROOT = _documents_dir() / "SKATE" if INSTALLED else EXE_DIR

os.environ["SKATE_ROOT"] = str(ROOT)
os.environ["PYTHONNOUSERSITE"] = "1"

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(EXE_DIR))
    sys.path.insert(0, str(EXE_DIR / "ui"))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from mcp_server.server import main

    main()
