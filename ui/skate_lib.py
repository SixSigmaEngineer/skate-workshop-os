"""
SKATE library — read and parse SKATE vault entries.

Centralizes filesystem access and frontmatter parsing so the FastAPI app
stays thin.
"""

from __future__ import annotations

import re
import os
import sys
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

if not hasattr(frontmatter, "load"):
    class _CompatPost:
        def __init__(self, content: str, **metadata):
            self.content = content
            self.metadata = metadata

    def _parse_scalar(value: str):
        value = value.strip()
        if value in {"[]", ""}:
            return [] if value == "[]" else ""
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            return [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
        return value.strip("'\"")

    def _compat_load(path: Path, encoding: str = "utf-8"):
        text = Path(path).read_text(encoding=encoding)
        metadata: dict = {}
        content = text
        if text.startswith("---\n"):
            _start, raw_meta, content = text.split("---", 2)
            current_key = None
            for line in raw_meta.splitlines():
                if not line.strip():
                    continue
                if line.startswith("  - ") and current_key:
                    metadata.setdefault(current_key, []).append(_parse_scalar(line[4:]))
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                current_key = key.strip()
                value = value.strip()
                metadata[current_key] = [] if value == "" else _parse_scalar(value)
            content = content.lstrip("\r\n")
        return _CompatPost(content, **metadata)

    def _format_value(value) -> str:
        if isinstance(value, list):
            if not value:
                return "[]"
            return "\n" + "\n".join(f"  - {item}" for item in value)
        return str(value)

    def _compat_dumps(post) -> str:
        lines = ["---"]
        for key, value in post.metadata.items():
            formatted = _format_value(value)
            if formatted.startswith("\n"):
                lines.append(f"{key}:{formatted}")
            else:
                lines.append(f"{key}: {formatted}")
        lines.append("---")
        lines.append(post.content)
        return "\n".join(lines)

    frontmatter.Post = _CompatPost
    frontmatter.load = _compat_load
    frontmatter.dumps = _compat_dumps

def _has_entries(root: Path) -> bool:
    conversations = root / "conversations"
    return conversations.exists() and any(conversations.rglob("*.md"))


def _candidate_roots() -> list[Path]:
    here_root = Path(__file__).resolve().parent.parent
    cwd = Path.cwd()
    home = Path.home()
    candidates = [
        Path(os.environ["SKATE_ROOT"]) if os.environ.get("SKATE_ROOT") else None,
        here_root,
        cwd,
        cwd.parent,
    ]
    for parent in [here_root, *here_root.parents, cwd, *cwd.parents]:
        candidates.append(parent)

    desktop = home / "OneDrive" / "Desktop"
    if desktop.exists():
        try:
            candidates.extend(desktop.glob("**/SKATE"))
        except OSError:
            pass

    seen: set[Path] = set()
    out: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _resolve_skate_root() -> Path:
    candidates = _candidate_roots()
    for root in candidates:
        if _has_entries(root):
            return root
    for root in candidates:
        if (root / "conversations").exists():
            return root
    return Path(os.environ.get("SKATE_ROOT", Path(__file__).resolve().parent.parent)).resolve()


SKATE_ROOT = _resolve_skate_root()
CONVERSATIONS = SKATE_ROOT / "conversations"
SESSIONS = SKATE_ROOT / "sessions"
REFERENCE = SKATE_ROOT / "reference"
LAST_LOAD_ERRORS: list[str] = []
GRIND_CACHE_DIR = SKATE_ROOT / ".cache" / "grind"

ENTRY_TYPES: dict[str, dict[str, str]] = {
    "note": {"label": "Note", "color": "#52657d"},
    "observation": {"label": "Observation", "color": "#2e5e8e"},
    "pain": {"label": "Pain", "color": "#c66060"},
    "quote": {"label": "Quote", "color": "#8e4a2e"},
    "hypothesis": {"label": "Hypothesis", "color": "#7f9eb2"},
    "decision": {"label": "Decision", "color": "#8c6d3f"},
    "recommendation": {"label": "Recommendation", "color": "#2f8a6e"},
    "action": {"label": "Action Item", "color": "#3b7fb2"},
    "risk": {"label": "Risk", "color": "#b94a48"},
    "question": {"label": "Open Question", "color": "#b97c2e"},
    "opportunity": {"label": "Opportunity", "color": "#b97c2e"},
    "solution": {"label": "Solution", "color": "#b88a21"},
    "insight": {"label": "Insight", "color": "#6b3fa0"},
    "process": {"label": "Process", "color": "#2f8a6e"},
}

RELATIONSHIP_TYPES: dict[str, str] = {
    "supports": "Supports",
    "contradicts": "Contradicts",
    "causes": "Causes",
    "leads_to": "Leads To",
    "references": "References",
    "similar_to": "Similar To",
}

CONSULTING_THEMES = [
    "Advisor Productivity",
    "Onboarding",
    "Change Management",
    "Compliance",
    "Customer Experience",
    "Scoping",
    "Gemba",
    "Knowledge Sharing",
    "Tool Fragmentation",
    "Data Quality",
    "Process Waste",
    "Governance",
    "Workshop Facilitation",
    "Organizational Learning",
]

UNASSIGNED_SESSION = "unassigned"


@dataclass
class Entry:
    """A single SKATE entry — markdown body plus frontmatter metadata."""

    path: Path
    title: str
    date: str
    entry_type: str = "note"
    session: str = ""
    session_label: str = ""
    session_status: str = "active"
    tags: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    status: str = ""
    related: list[str] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)
    source: str = ""
    body: str = ""
    lineup_status: str = ""
    lineup_kind: str = "action"
    owner: str = ""
    due_date: str = ""
    cadence: str = "once"
    last_completed: str = ""
    captured_from: str = ""

    @property
    def type_label(self) -> str:
        return ENTRY_TYPES.get(self.entry_type, ENTRY_TYPES["note"])["label"]

    @property
    def type_color(self) -> str:
        return ENTRY_TYPES.get(self.entry_type, ENTRY_TYPES["note"])["color"]

    @property
    def session_key(self) -> str:
        return self.session or UNASSIGNED_SESSION

    @property
    def session_display(self) -> str:
        if self.session_label:
            return self.session_label
        if self.session:
            return self.session.replace("-", " ").title()
        return "Unassigned"

    @property
    def rel_path(self) -> str:
        return self.path.relative_to(SKATE_ROOT).as_posix()

    @property
    def file_id(self) -> str:
        return self.path.relative_to(CONVERSATIONS).as_posix()

    @property
    def summary(self) -> str:
        """Extract the Summary section from the body, or first paragraph."""
        m = re.search(
            r"##\s*Summary\s*\n+(.*?)(?=\n##\s|\Z)", self.body, re.DOTALL
        )
        if m:
            return m.group(1).strip()
        # Fall back to first non-heading paragraph
        for para in self.body.split("\n\n"):
            stripped = para.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return ""


def _coerce_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [s.strip() for s in value.split(",") if s.strip()]
    return [str(value)]


def _coerce_relationships(value) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    relationships = []
    for item in value:
        if isinstance(item, dict):
            rel_type = str(item.get("type", "") or "").strip().lower().replace("-", "_")
            target = str(item.get("target", "") or item.get("to", "") or "").strip()
            note = str(item.get("note", "") or "").strip()
        else:
            rel_type = "references"
            target = str(item).strip()
            note = ""
        if not target:
            continue
        if rel_type not in RELATIONSHIP_TYPES:
            rel_type = "references"
        relationships.append({"type": rel_type, "target": target, "note": note})
    return relationships


def load_entry(path: Path) -> Entry:
    post = frontmatter.load(path, encoding="utf-8")
    meta = post.metadata
    entry_type = str(meta.get("type", meta.get("entry_type", "note")) or "note").strip().lower()
    if entry_type not in ENTRY_TYPES:
        entry_type = "note"
    return Entry(
        path=path,
        title=str(meta.get("title", path.stem)),
        date=str(meta.get("date", "")),
        entry_type=entry_type,
        session=str(meta.get("session", "") or "").strip(),
        session_label=str(meta.get("session_label", "") or "").strip(),
        session_status=str(meta.get("session_status", "active") or "active").strip(),
        tags=_coerce_list(meta.get("tags")),
        themes=_coerce_list(meta.get("themes")),
        participants=_coerce_list(meta.get("participants")),
        status=str(meta.get("status", "active") or "active"),
        related=_coerce_list(meta.get("related")),
        relationships=_coerce_relationships(meta.get("relationships")),
        source=str(meta.get("source", "")),
        body=post.content,
        lineup_status=str(meta.get("lineup_status", "") or "").strip().lower(),
        lineup_kind=str(meta.get("lineup_kind", "action") or "action").strip().lower(),
        owner=str(meta.get("owner", "") or "").strip(),
        due_date=str(meta.get("due_date", "") or "").strip(),
        cadence=str(meta.get("cadence", "once") or "once").strip().lower(),
        last_completed=str(meta.get("last_completed", "") or "").strip(),
        captured_from=str(meta.get("captured_from", "") or "").strip(),
    )


def load_all_entries() -> list[Entry]:
    """Load every entry under conversations/, sorted by date desc."""
    entries: list[Entry] = []
    LAST_LOAD_ERRORS.clear()
    if not CONVERSATIONS.exists():
        LAST_LOAD_ERRORS.append(f"Missing conversations folder: {CONVERSATIONS}")
        return entries
    for md in CONVERSATIONS.rglob("*.md"):
        try:
            entries.append(load_entry(md))
        except Exception as e:  # pragma: no cover - best-effort
            message = f"WARN: failed to load {md}: {e}"
            LAST_LOAD_ERRORS.append(message)
            print(message, file=sys.stderr)
    entries.sort(key=lambda e: (e.date or "", e.title), reverse=True)
    return entries


def _safe_session_filename(session_key: str) -> str:
    """Return a traversal-safe filename for generated session artifacts."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", (session_key or "").strip()).strip(".-")
    return safe or "unassigned"


def save_grind_snapshot(session_key: str, insights: dict, entries: list[Entry]) -> Path:
    """Persist the latest GRIND output so read-only agents can retrieve it.

    The snapshot is a rebuildable cache, not a second source of truth. It is
    stored under .cache/, which is already excluded from version control.
    """
    GRIND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = GRIND_CACHE_DIR / f"{_safe_session_filename(session_key)}.json"
    payload = {
        "schema_version": 1,
        "session": session_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note_count": len(entries),
        "note_ids": [entry.file_id for entry in entries],
        "insights": insights,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def load_grind_snapshot(session_key: str) -> dict | None:
    """Load a session's latest cached GRIND output, if one exists."""
    path = GRIND_CACHE_DIR / f"{_safe_session_filename(session_key)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("session") != session_key or not isinstance(payload.get("insights"), dict):
        return None
    return payload


def vault_diagnostics() -> dict:
    """Return loader diagnostics for the running app."""
    md_files = []
    if CONVERSATIONS.exists():
        md_files = [p for p in CONVERSATIONS.rglob("*.md")]
    candidate_rows = []
    for root in _candidate_roots()[:12]:
        conversations = root / "conversations"
        markdown_count = 0
        if conversations.exists():
            try:
                markdown_count = sum(1 for _ in conversations.rglob("*.md"))
            except OSError:
                markdown_count = -1
        candidate_rows.append(
            {
                "path": str(root),
                "has_conversations": conversations.exists(),
                "markdown_count": markdown_count,
            }
        )
    return {
        "skate_root": str(SKATE_ROOT),
        "conversations": str(CONVERSATIONS),
        "conversations_exists": CONVERSATIONS.exists(),
        "markdown_count": len(md_files),
        "sample_files": [str(p) for p in md_files[:10]],
        "load_errors": LAST_LOAD_ERRORS[-20:],
        "candidate_roots": candidate_rows,
    }


def find_entry_by_id(file_id: str) -> Optional[Entry]:
    """Look up an entry by its file_id (relative to conversations/)."""
    path = CONVERSATIONS / file_id
    if not path.exists() or not path.is_file():
        return None
    # Security: ensure the resolved path stays inside CONVERSATIONS
    try:
        path.resolve().relative_to(CONVERSATIONS.resolve())
    except ValueError:
        return None
    return load_entry(path)


def session_stats(entries: list[Entry]) -> list[dict]:
    """Aggregate entries by workshop/design session."""
    buckets: dict[str, dict] = {}
    for entry in entries:
        key = entry.session_key
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "label": entry.session_display,
                "status": entry.session_status or "active",
                "count": 0,
                "types": {},
            },
        )
        if entry.session_label and bucket["label"] == "Unassigned":
            bucket["label"] = entry.session_label
        bucket["count"] += 1
        bucket["types"][entry.entry_type] = bucket["types"].get(entry.entry_type, 0) + 1

    if SESSIONS.exists():
        for md in SESSIONS.rglob("*.md"):
            try:
                post = frontmatter.load(md, encoding="utf-8")
            except Exception:
                continue
            key = str(post.metadata.get("session", "") or md.parent.name or md.stem).strip()
            if not key:
                continue
            bucket = buckets.setdefault(
                key,
                {
                    "key": key,
                    "label": str(post.metadata.get("title", "") or key.replace("-", " ").title()),
                    "status": str(post.metadata.get("status", "active") or "active"),
                    "count": 0,
                    "types": {},
                },
            )
            # A session README is the session-level source of truth. Entries
            # retain legacy session metadata, but should not override a status
            # explicitly chosen for the session itself.
            bucket["label"] = str(post.metadata.get("title", "") or bucket["label"])
            bucket["status"] = str(post.metadata.get("status", "active") or "active")

    return sorted(
        buckets.values(),
        key=lambda row: (row["key"] == UNASSIGNED_SESSION, -row["count"], row["label"].lower()),
    )


def filter_entries(
    entries: list[Entry],
    session: Optional[str] = None,
    entry_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[Entry]:
    """Filter entries for session-scoped workshop views."""
    session = (session or "").strip()
    entry_type = (entry_type or "").strip().lower()
    date_from = (date_from or "").strip()
    date_to = (date_to or "").strip()

    out: list[Entry] = []
    for entry in entries:
        if session:
            if session == UNASSIGNED_SESSION:
                if entry.session:
                    continue
            elif entry.session != session:
                continue
        if entry_type and entry.entry_type != entry_type:
            continue
        if date_from and (not entry.date or entry.date < date_from):
            continue
        if date_to and (not entry.date or entry.date > date_to):
            continue
        out.append(entry)
    return out


def search_entries(
    entries: list[Entry],
    keyword: Optional[str] = None,
    theme: Optional[str] = None,
) -> list[Entry]:
    """Filter entries by keyword and/or theme."""
    results = []
    kw_lower = keyword.lower() if keyword else None
    theme_lower = theme.lower() if theme else None

    for entry in entries:
        if theme_lower:
            themes = [t.lower() for t in entry.themes + entry.tags]
            if not any(theme_lower in t for t in themes):
                continue
        if kw_lower:
            haystack = (
                entry.title
                + " "
                + entry.body
                + " "
                + " ".join(entry.tags)
                + " "
                + " ".join(entry.themes)
            ).lower()
            if kw_lower not in haystack:
                continue
        results.append(entry)
    return results


def _plain_excerpt(text: str, limit: int = 180) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"[-*]\s+", "", text)
    text = re.sub(r">\s*\[!\w+\]\s*", "", text)
    text = re.sub(r"(?m)^>\s?", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "..."


def _note_blocks(entry: Entry, block_type: str) -> list[dict]:
    shortcuts = {
        "pain": "P",
        "observation": "O",
        "action": "A",
        "question": "Q",
        "solution": "S",
        "recommendation": "R",
        "insight": "I",
    }
    pattern = re.compile(
        rf"(?im)^>\s*\[!{re.escape(block_type)}\]\s*(.*?)\n((?:^>.*(?:\n|$))*)"
    )
    blocks = []
    for match in pattern.finditer(entry.body or ""):
        heading = re.sub(r"\s+", " ", match.group(1).strip())
        content = re.sub(r"(?m)^>\s?", "", match.group(2)).strip()
        title = heading or f"{block_type.replace('-', ' ').title()} from {entry.title}"
        blocks.append(
            {
                "title": title,
                "summary": _plain_excerpt(content or entry.summary or entry.body or title),
                "source_url": f"/entry/{entry.file_id}",
                "session": entry.session_key,
            }
        )
    shortcut = shortcuts.get(block_type)
    if shortcut:
        # Accept live-capture bullets (``- #P:``), legacy bare markers
        # (``#P:``), and escaped markers used by some markdown editors.
        shortcut_pattern = re.compile(
            rf"(?im)^\s*(?:[-*]\s+)?\\?#{shortcut}:\s*(.+)$"
        )
        for match in shortcut_pattern.finditer(entry.body or ""):
            title = match.group(1).strip()
            blocks.append(
                {
                    "title": title or f"{block_type.replace('-', ' ').title()} from {entry.title}",
                    "summary": _plain_excerpt(title or entry.summary or entry.body),
                    "source_url": f"/entry/{entry.file_id}",
                    "session": entry.session_key,
                }
            )
    return blocks


def capture_markers(entry: Entry) -> dict[str, list[str]]:
    """Return SKATE's explicit inline workshop signals from one note."""
    marker_types = (
        "pain",
        "observation",
        "action",
        "question",
        "solution",
        "recommendation",
        "insight",
    )
    return {
        marker_type: [block["title"] for block in _note_blocks(entry, marker_type)]
        for marker_type in marker_types
    }


def _pain_score(entry: Entry) -> int:
    haystack = f"{entry.title} {entry.summary} {' '.join(entry.tags)}".lower()
    keywords = [
        "pain",
        "problem",
        "friction",
        "bottleneck",
        "delay",
        "confusing",
        "confusion",
        "manual",
        "waste",
        "hard",
        "difficult",
        "risk",
        "stuck",
        "unclear",
        "missing",
        "fails",
        "failure",
        "slow",
    ]
    score = 0
    score += sum(2 for word in keywords if word in haystack)
    if "?" in entry.summary:
        score += 1
    return score


def design_insights(entries: list[Entry], graph: dict | None = None) -> dict:
    """Generate lightweight workshop prompts from the current Grind scope."""
    graph = graph or graph_data(entries)
    marked_pains = []
    marked_observations = []
    marked_actions = []
    marked_questions = []
    marked_solutions = []
    marked_recommendations = []
    marked_insights = []
    for entry in entries:
        marked_pains.extend(_note_blocks(entry, "pain"))
        marked_observations.extend(_note_blocks(entry, "observation"))
        marked_actions.extend(_note_blocks(entry, "action"))
        marked_questions.extend(_note_blocks(entry, "question"))
        marked_solutions.extend(_note_blocks(entry, "solution"))
        marked_recommendations.extend(_note_blocks(entry, "recommendation"))
        marked_insights.extend(_note_blocks(entry, "insight"))

    marker_counts = {
        "pain": len(marked_pains),
        "observation": len(marked_observations),
        "action": len(marked_actions),
        "question": len(marked_questions),
        "solution": len(marked_solutions),
        "recommendation": len(marked_recommendations),
        "insight": len(marked_insights),
    }

    pain_candidates = []
    for entry in entries:
        score = _pain_score(entry)
        if score <= 0:
            continue
        pain_candidates.append((score, entry))

    pain_candidates.sort(key=lambda row: (-row[0], row[1].date or "", row[1].title))
    pains: list[dict] = []
    seen_titles: set[str] = set()
    for block in marked_pains[:10]:
        if block["title"] in seen_titles:
            continue
        seen_titles.add(block["title"])
        pains.append(
            {
                **block,
                "score": 10,
                "entry_type": "note",
                "capture_title": f"Pain: {block['title']}",
                "capture_summary": block["summary"],
                "capture_body": f"#P: {block['title']}\n\n{block['summary']}",
            }
        )

    for score, entry in pain_candidates[:10]:
        if entry.title in seen_titles:
            continue
        seen_titles.add(entry.title)
        summary = _plain_excerpt(entry.summary or entry.body or entry.title)
        pains.append(
            {
                "title": entry.title,
                "summary": summary,
                "score": score,
                "entry_type": entry.entry_type,
                "source_url": f"/entry/{entry.file_id}",
                "session": entry.session_key,
                "capture_title": f"Pain: {entry.title}",
                "capture_summary": summary,
                "capture_body": f"#P: {entry.title}\n\n{summary}",
            }
        )

    if not pains:
        connected = sorted(
            graph["nodes"],
            key=lambda node: (-node.get("value", 0), node.get("title_full", "")),
        )
        for node in connected[:3]:
            pains.append(
                {
                    "title": f"Possible friction around {node['title_full']}",
                    "summary": f"Several notes connect around {node['title_full']}. Review this cluster for repeated friction, unmet needs, or workflow gaps.",
                    "score": node.get("value", 1),
                    "entry_type": "note",
                    "source_url": node.get("url", "#"),
                    "session": node.get("session", ""),
                    "capture_title": f"Pain: {node['title_full']}",
                    "capture_summary": f"Potential pain point found in the {node['title_full']} cluster.",
                    "capture_body": f"#P: Possible friction around {node['title_full']}\n\nPotential pain point found in the {node['title_full']} cluster.",
                }
            )

    hmw_prompts = []
    seen_prompts: set[str] = set()
    for block in marked_questions[:10]:
        prompt = block["title"]
        if not re.match(r"(?i)^how might we\b", prompt):
            prompt = f"How might we answer: {prompt.rstrip('?')}?"
        if prompt in seen_prompts:
            continue
        seen_prompts.add(prompt)
        hmw_prompts.append(
            {
                "prompt": prompt,
                "source_title": block["title"],
                "capture_title": f"HMW: {block['title']}",
                "capture_summary": f"{prompt}\n\nSource: {block['summary']}",
                "capture_body": f"#Q: {prompt}\n\nSource: {block['summary']}",
            }
        )

    for pain in pains[:10]:
        if len(hmw_prompts) >= 10:
            break
        short = pain["title"]
        short = re.sub(r"^(pain|problem|friction)\s*:\s*", "", short, flags=re.I)
        prompt = f"How might we reduce friction around {short}?"
        if prompt in seen_prompts:
            continue
        seen_prompts.add(prompt)
        hmw_prompts.append(
            {
                "prompt": prompt,
                "source_title": pain["title"],
                "capture_title": f"HMW: {short}",
                "capture_summary": f"How might we reduce friction around {short}?\n\nSource: {pain['summary']}",
                "capture_body": f"#Q: {prompt}\n\nSource: {pain['summary']}",
            }
        )

    solutions = []
    seen_solutions: set[str] = set()
    for block in marked_solutions[:10]:
        if block["title"] in seen_solutions:
            continue
        seen_solutions.add(block["title"])
        solutions.append(
            {
                "title": block["title"],
                "summary": block["summary"],
                "source_url": block["source_url"],
                "capture_title": f"Solution: {block['title']}",
                "capture_summary": block["summary"],
                "capture_body": f"#S: {block['title']}\n\n{block['summary']}",
            }
        )

    for block in marked_recommendations[:10]:
        if len(solutions) >= 10:
            break
        title = f"Recommended move: {block['title']}"
        if title in seen_solutions:
            continue
        seen_solutions.add(title)
        solutions.append(
            {
                "title": title,
                "summary": block["summary"],
                "source_url": block["source_url"],
                "capture_title": title,
                "capture_summary": block["summary"],
                "capture_body": f"#R: {block['title']}\n\n{block['summary']}",
            }
        )

    for block in marked_actions[:10]:
        if len(solutions) >= 10:
            break
        title = f"Next experiment: {block['title']}"
        if title in seen_solutions:
            continue
        seen_solutions.add(title)
        solutions.append(
            {
                "title": title,
                "summary": block["summary"],
                "source_url": block["source_url"],
                "capture_title": title,
                "capture_summary": block["summary"],
                "capture_body": f"#A: {block['title']}\n\n{block['summary']}",
            }
        )

    for index, pain in enumerate(pains[:10]):
        if len(solutions) >= 10:
            break
        idea = "Create a small testable workflow change: define the trigger, the next best action, and the evidence that the pain is improving."
        source_url = pain["source_url"]
        title = f"Starter solution: {pain['title']}"
        if title in seen_solutions:
            continue
        seen_solutions.add(title)
        solutions.append(
            {
                "title": title,
                "summary": idea,
                "source_url": source_url,
                "capture_title": f"Solution: {pain['title']}",
                "capture_summary": f"{idea}\n\nPain source: {pain['summary']}",
                "capture_body": f"#S: {title}\n\n{idea}\n\nPain source: {pain['summary']}",
            }
        )

    return {
        "pains": pains,
        "hmw_prompts": hmw_prompts,
        "solutions": solutions,
        "marker_counts": marker_counts,
    }


def theme_stats(entries: list[Entry]) -> list[dict]:
    """Aggregate consultant themes from explicit themes and tag fallbacks."""
    counts: dict[str, int] = {}
    for entry in entries:
        themes = entry.themes or [
            tag.replace("-", " ").title()
            for tag in entry.tags
            if tag.replace("-", " ").title() in CONSULTING_THEMES
        ]
        for theme in themes:
            clean = theme.strip()
            if clean:
                counts[clean] = counts.get(clean, 0) + 1
    return [
        {"theme": theme, "count": count}
        for theme, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    ]


def _draft_consulting_graph_data(entries: list[Entry]) -> dict:
    """Build the final consulting-native insight graph."""
    nodes_by_id: dict[str, dict] = {}
    for entry in entries:
        color = ENTRY_TYPES.get(entry.entry_type, ENTRY_TYPES["note"])["color"]
        nodes_by_id[entry.file_id] = {
            "id": entry.file_id,
            "label": entry.title if len(entry.title) <= 40 else entry.title[:37] + "...",
            "title_full": entry.title,
            "entry_type": entry.entry_type,
            "type_label": entry.type_label,
            "type_color": entry.type_color,
            "session": entry.session_key,
            "session_label": entry.session_display,
            "themes": entry.themes,
            "date": entry.date,
            "color": color,
            "url": f"/entry/{entry.file_id}",
            "value": 1,
        }

    edges: list[dict] = []
    used_relationships: set[tuple[str, str, str]] = set()
    for entry in entries:
        legacy_relationships = [{"type": "references", "target": rel, "note": ""} for rel in entry.related]
        for rel in [*entry.relationships, *legacy_relationships]:
            target_id = rel.get("target", "")
            target = next(
                (
                    other
                    for other in entries
                    if other.path.name == target_id or other.file_id.endswith(target_id)
                ),
                None,
            )
            if not target or target.file_id == entry.file_id:
                continue
            rel_type = rel.get("type", "references")
            key = (*tuple(sorted([entry.file_id, target.file_id])), rel_type)
            if key in used_relationships:
                continue
            used_relationships.add(key)
            edges.append(
                {
                    "from": entry.file_id,
                    "to": target.file_id,
                    "type": rel_type,
                    "label": RELATIONSHIP_TYPES.get(rel_type, "References"),
                    "note": rel.get("note", ""),
                    "dashes": rel_type in {"contradicts", "references", "similar_to"},
                }
            )

    by_theme: dict[str, list[Entry]] = {}
    for entry in entries:
        for theme in entry.themes:
            by_theme.setdefault(theme, []).append(entry)

    used_theme_pairs: set[tuple[str, str]] = set()
    for theme, group in by_theme.items():
        ordered = sorted(group, key=lambda item: (item.date or "", item.title), reverse=True)
        for first, second in zip(ordered, ordered[1:]):
            key = tuple(sorted([first.file_id, second.file_id]))
            if key in used_theme_pairs:
                continue
            used_theme_pairs.add(key)
            edges.append(
                {
                    "from": first.file_id,
                    "to": second.file_id,
                    "type": "similar_to",
                    "shared": [theme],
                    "label": theme,
                    "dashes": False,
                }
            )

    nodes = list(nodes_by_id.values())
    legend = [
        {
            "letter": entry_type,
            "label": ENTRY_TYPES.get(entry_type, ENTRY_TYPES["note"])["label"],
            "color": ENTRY_TYPES.get(entry_type, ENTRY_TYPES["note"])["color"],
        }
        for entry_type in sorted({node["entry_type"] for node in nodes if node["entry_type"]})
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "legend": legend,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "theme_edges": sum(1 for edge in edges if edge["type"] == "similar_to"),
            "relationship_edges": sum(1 for edge in edges if edge["type"] != "similar_to"),
        },
    }


def _draft_consulting_theme_graph_data(entries: list[Entry]) -> dict:
    """Build an insight graph for consultant memory."""
    nodes_by_id: dict[str, dict] = {}
    for entry in entries:
        color = ENTRY_TYPES.get(entry.entry_type, ENTRY_TYPES["note"])["color"]
        nodes_by_id[entry.file_id] = {
            "id": entry.file_id,
            "label": entry.title if len(entry.title) <= 40 else entry.title[:37] + "...",
            "title_full": entry.title,
            "entry_type": entry.entry_type,
            "type_label": entry.type_label,
            "type_color": entry.type_color,
            "session": entry.session_key,
            "session_label": entry.session_display,
            "themes": entry.themes,
            "date": entry.date,
            "color": color,
            "url": f"/entry/{entry.file_id}",
            "value": 1,
        }

    edges: list[dict] = []
    used_pairs: set[tuple[str, str, str]] = set()
    by_id = {entry.file_id: entry for entry in entries}

    for entry in entries:
        legacy_relationships = [{"type": "references", "target": rel, "note": ""} for rel in entry.related]
        for rel in [*entry.relationships, *legacy_relationships]:
            target_id = rel.get("target", "")
            target = next(
                (
                    other
                    for other in entries
                    if other.path.name == target_id or other.file_id.endswith(target_id)
                ),
                None,
            )
            if not target:
                continue
            rel_type = rel.get("type", "references")
            pair = (*tuple(sorted([entry.file_id, target.file_id])), rel_type)
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            edges.append(
                {
                    "from": entry.file_id,
                    "to": target.file_id,
                    "type": rel_type,
                    "label": RELATIONSHIP_TYPES.get(rel_type, "References"),
                    "note": rel.get("note", ""),
                    "dashes": rel_type in {"contradicts", "references", "similar_to"},
                }
            )
            nodes_by_id[entry.file_id]["value"] += 1
            nodes_by_id[target.file_id]["value"] += 1

    by_theme: dict[str, list[Entry]] = {}
    for entry in entries:
        for theme in entry.themes:
            by_theme.setdefault(theme, []).append(entry)

    theme_pairs: set[tuple[str, str]] = set()
    for theme, group in by_theme.items():
        ordered = sorted(group, key=lambda item: (item.date or "", item.title), reverse=True)
        for first, second in zip(ordered, ordered[1:]):
            if first.file_id not in by_id or second.file_id not in by_id:
                continue
            pair = tuple(sorted([first.file_id, second.file_id]))
            if pair in theme_pairs:
                continue
            theme_pairs.add(pair)
            edges.append(
                {
                    "from": first.file_id,
                    "to": second.file_id,
                    "type": "similar_to",
                    "shared": [theme],
                    "label": theme,
                    "dashes": False,
                }
            )

    nodes = list(nodes_by_id.values())
    present_types = sorted({node["entry_type"] for node in nodes if node["entry_type"]})
    legend = [
        {
            "letter": entry_type,
            "label": ENTRY_TYPES.get(entry_type, ENTRY_TYPES["note"])["label"],
            "color": ENTRY_TYPES.get(entry_type, ENTRY_TYPES["note"])["color"],
        }
        for entry_type in present_types
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "legend": legend,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "theme_edges": sum(1 for edge in edges if edge["type"] == "similar_to"),
            "relationship_edges": sum(1 for edge in edges if edge["type"] != "similar_to"),
        },
    }


def graph_data(entries: list[Entry]) -> dict:
    """Build an insight graph for consultant memory.

    Explicit typed relationships are the main rails. Shared themes add a
    capped similarity layer so the graph shows evidence-to-insight structure.
    """
    nodes_by_id: dict[str, dict] = {}
    for entry in entries:
        color = ENTRY_TYPES.get(entry.entry_type, ENTRY_TYPES["note"])["color"]
        label = entry.title if len(entry.title) <= 40 else entry.title[:37] + "..."
        nodes_by_id[entry.file_id] = {
            "id": entry.file_id,
            "label": label,
            "title_full": entry.title,
            "entry_type": entry.entry_type,
            "type_label": entry.type_label,
            "type_color": entry.type_color,
            "session": entry.session_key,
            "session_label": entry.session_display,
            "themes": entry.themes,
            "date": entry.date,
            "color": color,
            "url": f"/entry/{entry.file_id}",
            "value": 1,
        }

    edges: list[dict] = []
    relationship_pairs: set[tuple[str, str, str]] = set()
    relationship_degree: dict[str, int] = {entry.file_id: 0 for entry in entries}
    theme_pairs: set[tuple[str, str]] = set()
    theme_degree: dict[str, int] = {entry.file_id: 0 for entry in entries}

    for entry in entries:
        legacy_relationships = [
            {"type": "references", "target": rel, "note": ""}
            for rel in entry.related
        ]
        for rel in [*entry.relationships, *legacy_relationships]:
            target_id = rel.get("target", "")
            target = next(
                (
                    other
                    for other in entries
                    if other.path.name == target_id or other.file_id.endswith(target_id)
                ),
                None,
            )
            if not target or target.file_id == entry.file_id:
                continue
            rel_type = rel.get("type", "references")
            pair = (*tuple(sorted([entry.file_id, target.file_id])), rel_type)
            if pair in relationship_pairs:
                continue
            if relationship_degree[entry.file_id] >= 4 or relationship_degree[target.file_id] >= 4:
                continue
            relationship_pairs.add(pair)
            edges.append(
                {
                    "from": entry.file_id,
                    "to": target.file_id,
                    "type": rel_type,
                    "label": RELATIONSHIP_TYPES.get(rel_type, "References"),
                    "note": rel.get("note", ""),
                    "dashes": rel_type in {"contradicts", "references", "similar_to"},
                }
            )
            relationship_degree[entry.file_id] += 1
            relationship_degree[target.file_id] += 1
            nodes_by_id[entry.file_id]["value"] += 1
            nodes_by_id[target.file_id]["value"] += 1

    by_theme: dict[str, list[Entry]] = {}
    for entry in entries:
        for theme in entry.themes:
            by_theme.setdefault(theme, []).append(entry)

    for theme, group in by_theme.items():
        ordered = sorted(group, key=lambda item: (item.date or "", item.title), reverse=True)
        for first, second in zip(ordered, ordered[1:]):
            pair = tuple(sorted([first.file_id, second.file_id]))
            if pair in theme_pairs:
                continue
            if theme_degree[first.file_id] >= 2 or theme_degree[second.file_id] >= 2:
                continue
            theme_pairs.add(pair)
            edges.append(
                {
                    "from": first.file_id,
                    "to": second.file_id,
                    "type": "similar_to",
                    "shared": [theme],
                    "label": theme,
                    "dashes": False,
                }
            )
            theme_degree[first.file_id] += 1
            theme_degree[second.file_id] += 1

    nodes = list(nodes_by_id.values())
    present_types = sorted({node["entry_type"] for node in nodes if node["entry_type"]})
    legend = [
        {
            "letter": entry_type,
            "label": ENTRY_TYPES.get(entry_type, ENTRY_TYPES["note"])["label"],
            "color": ENTRY_TYPES.get(entry_type, ENTRY_TYPES["note"])["color"],
        }
        for entry_type in present_types
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "legend": legend,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "theme_edges": sum(1 for edge in edges if edge["type"] == "similar_to"),
            "relationship_edges": sum(1 for edge in edges if edge["type"] != "similar_to"),
        },
    }
