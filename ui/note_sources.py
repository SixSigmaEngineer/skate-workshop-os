"""Read preserved originals without mixing raw text into cleaned evidence."""
from pathlib import Path
import re

SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9_-]*/attachments/original-note-[A-Za-z0-9._-]+\.txt")
SOURCE_LINK = re.compile(r"\]\((?P<link>(?:attachments/|/entry/[a-z0-9][a-z0-9_-]*/attachments/)original-note-[A-Za-z0-9._-]+\.txt)\)")
MAX_CHARS = 12000
MAX_BYTES = 25 * 1024 * 1024


def source_path(conversations: Path, source_id: str) -> Path:
    if not SOURCE_ID.fullmatch(source_id):
        raise ValueError("Original source not found.")
    root = conversations.resolve()
    path = (root / source_id).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Original source not found.")
    return path


def originals(body: str, session: str, conversations: Path) -> list[dict]:
    rows = []
    seen = set()
    # New archives have stable links; older notes used session-relative links.
    session = re.sub(r"[^a-z0-9]+", "-", session.lower()).strip("-") or "unassigned"
    for match in SOURCE_LINK.finditer(body):
        link = match["link"]
        source_id = link.removeprefix("/entry/") if link.startswith("/entry/") else f"{session}/{link}"
        if source_id in seen:
            continue
        seen.add(source_id)
        try:
            path = source_path(conversations, source_id)
            rows.append({"source_id": source_id, "label": "Original notes / transcript",
                         "url": f"/entry/{source_id}", "size_bytes": path.stat().st_size})
        except (ValueError, OSError):
            continue
    return rows


def read_original(conversations: Path, source_id: str, offset: int = 0, max_chars: int = MAX_CHARS) -> dict:
    path = source_path(conversations, source_id)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Original exceeds the supported text size.")
    # Disable newline conversion to preserve the archived text exactly.
    with path.open(encoding="utf-8", newline="") as stream:
        text = stream.read()
    start = max(0, int(offset))
    limit = max(1, min(MAX_CHARS, int(max_chars)))
    end = min(len(text), start + limit)
    return {"source_id": source_id, "text": text[start:end], "offset": start,
            "total_chars": len(text), "next_offset": end if end < len(text) else None,
            "text_truncated": end < len(text), "kind": "original_unedited"}
