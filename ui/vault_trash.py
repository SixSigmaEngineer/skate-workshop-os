"""Recoverable, vault-local removal. Attachments and other notes stay in place."""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

LOCK = threading.RLock()


class TrashError(ValueError):
    pass


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise TrashError("The file is outside this vault.")
    return resolved


def _original(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (not parts or parts[0] not in {"conversations", "sessions"}
            or any(part in {".", ".."} for part in parts)
            or "\\" in relative or ":" in relative or not relative.endswith(".md")):
        raise TrashError("This is not a note or session file.")
    return _inside(root, root.joinpath(*parts))


def _folder(root: Path, batch_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        raise TrashError("That Trash item was not found.")
    return _inside(root, root / ".trash" / batch_id)


def _save(folder: Path, manifest: dict) -> None:
    temporary = folder / "manifest.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(folder / "manifest.json")


def move(root: Path, paths: list[Path], *, title: str, kind: str, session: str) -> dict:
    with LOCK:
        relatives = list(dict.fromkeys(path.relative_to(root).as_posix() for path in paths))
        sources = [_original(root, relative) for relative in relatives]
        if not sources or any(not path.is_file() for path in sources):
            raise TrashError("The selected files changed. Refresh the page and try again.")
        batch_id = uuid.uuid4().hex
        folder = _folder(root, batch_id)
        folder.mkdir(parents=True, exist_ok=False)
        manifest = {"id": batch_id, "title": title, "kind": kind, "session": session,
                    "created_at": datetime.now(timezone.utc).isoformat(), "state": "pending",
                    "paths": relatives, "note_count": sum(p.startswith("conversations/") for p in relatives)}
        _save(folder, manifest)
        moved = []
        try:
            for relative, source in zip(relatives, sources):
                destination = _inside(folder, folder / "files" / relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
                moved.append((source, destination))
            manifest["state"] = "trashed"
            _save(folder, manifest)
        except OSError:
            # If rollback cannot complete, the pending manifest still makes the
            # remaining archived files available through Trash for recovery.
            for source, destination in reversed(moved):
                if not source.exists():
                    destination.rename(source)
            raise
        return manifest


def items(root: Path) -> list[dict]:
    with LOCK:
        trash = _inside(root, root / ".trash")
        results = []
        for path in trash.glob("*/manifest.json"):
            try:
                folder = _folder(root, path.parent.name)
                manifest = json.loads(_inside(folder, path).read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    continue
                if manifest.get("state") not in {"pending", "trashed"}:
                    continue
                # A damaged timestamp must not block recovery of otherwise
                # valid files or sorting of the entire Trash page.
                if not isinstance(manifest.get("created_at"), str):
                    manifest["created_at"] = ""
                paths = manifest["paths"]
                if not isinstance(paths, list):
                    continue
                stored = []
                for relative in paths:
                    _original(root, relative)
                    if _inside(folder, folder / "files" / relative).is_file():
                        stored.append(relative)
                if stored:
                    results.append({**manifest, "id": path.parent.name,
                                    "note_count": sum(p.startswith("conversations/") for p in stored)})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(results, key=lambda item: item.get("created_at", ""), reverse=True)


def restore(root: Path, batch_id: str) -> dict:
    with LOCK:
        folder = _folder(root, batch_id)
        manifest = next((row for row in items(root) if row["id"] == batch_id), None)
        if manifest is None:
            raise TrashError("That Trash item was not found or has already been restored.")
        pairs = []
        for relative in manifest["paths"]:
            destination = _original(root, relative)
            source = _inside(folder, folder / "files" / relative)
            if not source.is_file():
                continue
            if destination.exists():
                raise TrashError("A note or session now uses the same filename. Rename or move it before restoring; nothing was overwritten.")
            pairs.append((source, destination))
        moved = []
        try:
            for source, destination in pairs:
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
                moved.append((source, destination))
            manifest["state"] = "restored"
            _save(folder, manifest)
        except OSError:
            for source, destination in reversed(moved):
                if not source.exists():
                    destination.rename(source)
            raise
        return manifest
