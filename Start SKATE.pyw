"""Windowless SKATE launcher for Windows.

Double-click this file to start SKATE without opening a Command Prompt.
It creates/uses .build-venv, installs missing dependencies, then starts the
tray-backed local app with pythonw.exe.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
VENV_DIR = ROOT / ".build-venv"
REQS = UI_DIR / "requirements.txt"
APP = UI_DIR / "app.py"
LOG = ROOT / "skate-launch.log"
CREATE_NO_WINDOW = 0x08000000


def log(message: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


def alert(title: str, message: str) -> None:
    log(f"{title}: {message}")
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)


def run_hidden(args: list[str], cwd: Path = UI_DIR) -> subprocess.CompletedProcess:
    env = dict(**os.environ, SKATE_ROOT=str(ROOT))
    return subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def find_python() -> list[str] | None:
    py = shutil.which("py")
    if py:
        return [py, "-3"]
    python = shutil.which("python")
    if python:
        return [python]
    return None


def venv_python(console: bool = False) -> Path:
    name = "python.exe" if console else "pythonw.exe"
    candidate = VENV_DIR / "Scripts" / name
    if candidate.exists():
        return candidate
    return VENV_DIR / "Scripts" / "python.exe"


def ensure_venv() -> bool:
    python = find_python()
    if python is None:
        alert(
            "SKATE needs Python",
            "Python 3.10 or newer was not found. Install Python, then launch SKATE again.",
        )
        return False

    needs_venv = not (VENV_DIR / "Scripts" / "activate.bat").exists()
    if not needs_venv:
        probe = run_hidden([str(venv_python(console=True)), "--version"])
        needs_venv = probe.returncode != 0

    if needs_venv:
        result = run_hidden([*python, "-m", "venv", "--clear", str(VENV_DIR)])
        if result.returncode != 0:
            alert(
                "SKATE setup failed",
                "Could not refresh SKATE's local environment. Quit any running SKATE windows, then launch again.",
            )
            return False

    check = run_hidden(
        [
            str(venv_python(console=True)),
            "-c",
            "import fastapi, uvicorn, jinja2, frontmatter, markdown, pystray, PIL, whisper",
        ]
    )
    if check.returncode == 0:
        return True

    result = run_hidden(
        [
            str(venv_python(console=True)),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
        ]
    )
    if result.returncode != 0:
        alert("SKATE setup failed", "Could not update pip in SKATE's local environment.")
        return False

    result = run_hidden(
        [
            str(venv_python(console=True)),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "-r",
            str(REQS),
        ]
    )
    if result.returncode != 0:
        alert(
            "SKATE setup failed",
            "Could not install SKATE's dependencies. Check your internet connection, then try again.",
        )
        return False

    return True


def main() -> None:
    log(f"Launching SKATE from {ROOT}")
    log(f"Using runtime {VENV_DIR}")
    if not ensure_venv():
        return

    proc = subprocess.Popen(
        [str(venv_python()), str(APP)],
        cwd=str(UI_DIR),
        env=dict(**os.environ, SKATE_ROOT=str(ROOT)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    log(f"Started SKATE app process {proc.pid}")


if __name__ == "__main__":
    main()
