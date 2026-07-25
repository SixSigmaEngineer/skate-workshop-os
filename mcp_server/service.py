"""Read-only, governance-aware access to SKATE workshop memory.

This module contains no MCP transport code, which keeps the retrieval and
security rules easy to test independently of a particular client.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

import embeddings  # noqa: E402
from skate_lib import (  # noqa: E402
    Entry,
    SKATE_ROOT,
    capture_markers,
    design_insights,
    filter_entries,
    find_entry_by_id,
    graph_data,
    load_all_entries,
    load_grind_snapshot,
    session_stats,
)


MAX_TOP_K = 20
MAX_BODY_CHARS = 12_000
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]+")


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _active_session_rows(entries: list[Entry]) -> list[dict[str, Any]]:
    return [
        row
        for row in session_stats(entries)
        if str(row.get("status", "active")).strip().lower() != "inactive"
    ]


def _active_entries(entries: list[Entry] | None = None) -> tuple[list[Entry], list[dict[str, Any]]]:
    entries = entries if entries is not None else load_all_entries()
    rows = _active_session_rows(entries)
    active_sessions = {str(row["key"]) for row in rows}
    governed = [
        entry
        for entry in entries
        if entry.status.strip().lower() != "inactive" and entry.session_key in active_sessions
    ]
    return governed, rows


def _session_or_error(session: str, entries: list[Entry]) -> tuple[list[Entry], dict[str, Any] | None]:
    session = (session or "").strip()
    governed, rows = _active_entries(entries)
    row = next((candidate for candidate in rows if candidate["key"] == session), None)
    if row is None:
        return [], {
            "error": "Session not found or inactive.",
            "session": session,
            "available_sessions": [candidate["key"] for candidate in rows],
        }
    return filter_entries(governed, session=session), None


def _lexical_score(query: str, entry: Entry) -> float:
    terms = [term.lower() for term in TOKEN_PATTERN.findall(query)]
    if not terms:
        return 0.0
    title = entry.title.lower()
    themes = " ".join(entry.themes + entry.tags).lower()
    body = f"{entry.summary} {entry.body}".lower()
    score = 0.0
    phrase = query.strip().lower()
    if phrase and phrase in title:
        score += 12.0
    elif phrase and phrase in body:
        score += 5.0
    for term in terms:
        score += title.count(term) * 5.0
        score += themes.count(term) * 3.0
        score += min(body.count(term), 8) * 1.0
    return score


def _approx_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _excerpt(entry: Entry, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", entry.summary or entry.body or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rsplit(" ", 1)[0] + "..."


def _entry_card(entry: Entry, excerpt_chars: int = 900) -> dict[str, Any]:
    markers = capture_markers(entry)
    return {
        "memory_id": entry.file_id,
        "title": entry.title,
        "date": entry.date,
        "type": entry.entry_type,
        "type_label": entry.type_label,
        "session": entry.session_key,
        "session_label": entry.session_display,
        "themes": entry.themes,
        "tags": entry.tags,
        "source": entry.source,
        "excerpt": _excerpt(entry, excerpt_chars),
        "signals": {name: values for name, values in markers.items() if values},
        "relationship_count": len(entry.relationships) + len(entry.related),
        "uri": f"skate://memory/{entry.file_id}",
    }


def server_info() -> dict[str, Any]:
    entries = load_all_entries()
    governed, rows = _active_entries(entries)
    try:
        retrieval = embeddings.backend_status()
    except Exception:
        retrieval = {"semantic": False, "backend": None, "model": None, "note": "lexical-only"}
    return {
        "name": "SKATE Workshop Memory",
        "mode": "read-only",
        "vault_root": str(SKATE_ROOT),
        "active_session_count": len(rows),
        "active_memory_count": len(governed),
        "retrieval": retrieval,
        "governance": "Inactive notes and inactive sessions are excluded from every MCP result.",
    }


def list_active_sessions() -> dict[str, Any]:
    entries = load_all_entries()
    governed, rows = _active_entries(entries)
    by_session = Counter(entry.session_key for entry in governed)
    sessions = []
    for row in rows:
        key = str(row["key"])
        sessions.append(
            {
                "session": key,
                "title": row.get("label", key),
                "status": "active",
                "memory_count": by_session.get(key, 0),
                "types": row.get("types", {}),
                "uri": f"skate://session/{key}",
            }
        )
    return {"count": len(sessions), "sessions": sessions}


def search_memory(query: str, session: str = "", top_k: int = 5) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"error": "query is required", "results": []}
    all_entries = load_all_entries()
    governed, _rows = _active_entries(all_entries)
    if session.strip():
        candidates, error = _session_or_error(session, all_entries)
        if error:
            return {**error, "query": query, "results": []}
    else:
        candidates = governed
    limit = _clamp(top_k, 1, MAX_TOP_K)
    ranked, mode = embeddings.rank_entries(
        candidates,
        query,
        lambda entry: _lexical_score(query, entry),
        top_k=limit,
    )
    cards = [_entry_card(entry) for entry in ranked]
    eligible_chars = sum(len(entry.body or "") for entry in candidates)
    returned_chars = sum(len(card["excerpt"]) for card in cards)
    reduction = 0.0
    if eligible_chars:
        reduction = max(0.0, 100.0 * (1.0 - (returned_chars / eligible_chars)))
    return {
        "query": query,
        "session": session.strip() or None,
        "retrieval_mode": mode,
        "eligible_memory_count": len(candidates),
        "returned_memory_count": len(cards),
        "estimated_full_context_tokens": _approx_tokens("".join(entry.body or "" for entry in candidates)),
        "estimated_returned_excerpt_tokens": _approx_tokens("".join(card["excerpt"] for card in cards)),
        "estimated_context_reduction_percent": round(reduction, 1),
        "results": cards,
    }


def get_memory_object(memory_id: str, max_body_chars: int = MAX_BODY_CHARS) -> dict[str, Any]:
    entry = find_entry_by_id((memory_id or "").strip())
    if entry is None:
        return {"error": "Memory object not found.", "memory_id": memory_id}
    governed, _rows = _active_entries()
    allowed_ids = {candidate.file_id for candidate in governed}
    if entry.file_id not in allowed_ids:
        return {"error": "Memory object is inactive or belongs to an inactive session.", "memory_id": memory_id}
    limit = _clamp(max_body_chars, 1000, MAX_BODY_CHARS)
    body = entry.body or ""
    result = _entry_card(entry, excerpt_chars=1200)
    result.update(
        {
            "status": "active",
            "participants": entry.participants,
            "body": body[:limit],
            "body_truncated": len(body) > limit,
            "relationships": entry.relationships
            + [{"type": "references", "target": target, "note": ""} for target in entry.related],
        }
    )
    return result


def get_session_context(session: str, query: str = "", top_k: int = 8) -> dict[str, Any]:
    all_entries = load_all_entries()
    candidates, error = _session_or_error(session, all_entries)
    if error:
        return error
    limit = _clamp(top_k, 1, MAX_TOP_K)
    if query.strip():
        ranked, mode = embeddings.rank_entries(
            candidates,
            query,
            lambda entry: _lexical_score(query, entry),
            top_k=limit,
        )
    else:
        ranked = sorted(candidates, key=lambda entry: (entry.date, entry.title), reverse=True)[:limit]
        mode = "recent"
    type_counts = Counter(entry.entry_type for entry in candidates)
    theme_counts = Counter(theme for entry in candidates for theme in entry.themes)
    return {
        "session": session,
        "query": query.strip() or None,
        "retrieval_mode": mode,
        "active_memory_count": len(candidates),
        "type_counts": dict(type_counts.most_common()),
        "top_themes": dict(theme_counts.most_common(12)),
        "evidence": [_entry_card(entry, excerpt_chars=1200) for entry in ranked],
    }


def _resolve_target(target: str, entries: list[Entry]) -> Entry | None:
    target = (target or "").strip().replace("\\", "/")
    return next(
        (
            entry
            for entry in entries
            if entry.file_id == target or entry.path.name == target or entry.file_id.endswith("/" + target)
        ),
        None,
    )


def trace_evidence(memory_id: str, depth: int = 1, max_items: int = 20) -> dict[str, Any]:
    start = get_memory_object(memory_id, max_body_chars=3000)
    if start.get("error"):
        return start
    governed, _rows = _active_entries()
    by_id = {entry.file_id: entry for entry in governed}
    root = by_id[start["memory_id"]]
    depth = _clamp(depth, 1, 3)
    max_items = _clamp(max_items, 1, 50)
    queue: deque[tuple[Entry, int]] = deque([(root, 0)])
    visited = {root.file_id}
    links: list[dict[str, Any]] = []

    while queue and len(links) < max_items:
        current, level = queue.popleft()
        if level >= depth:
            continue
        outgoing = current.relationships + [
            {"type": "references", "target": target, "note": ""} for target in current.related
        ]
        for relationship in outgoing:
            target = _resolve_target(str(relationship.get("target", "")), governed)
            if target is None:
                continue
            links.append(
                {
                    "from": current.file_id,
                    "to": target.file_id,
                    "direction": "outgoing",
                    "type": relationship.get("type", "references"),
                    "note": relationship.get("note", ""),
                    "evidence": _entry_card(target, excerpt_chars=500),
                }
            )
            if target.file_id not in visited:
                visited.add(target.file_id)
                queue.append((target, level + 1))
            if len(links) >= max_items:
                break

        for candidate in governed:
            if len(links) >= max_items:
                break
            relationships = candidate.relationships + [
                {"type": "references", "target": target, "note": ""} for target in candidate.related
            ]
            for relationship in relationships:
                target = _resolve_target(str(relationship.get("target", "")), governed)
                if target is None or target.file_id != current.file_id:
                    continue
                links.append(
                    {
                        "from": candidate.file_id,
                        "to": current.file_id,
                        "direction": "incoming",
                        "type": relationship.get("type", "references"),
                        "note": relationship.get("note", ""),
                        "evidence": _entry_card(candidate, excerpt_chars=500),
                    }
                )
                if candidate.file_id not in visited:
                    visited.add(candidate.file_id)
                    queue.append((candidate, level + 1))
                break

    return {
        "root": _entry_card(root, excerpt_chars=1000),
        "depth": depth,
        "link_count": len(links),
        "links": links,
    }


def get_grind_outputs(session: str) -> dict[str, Any]:
    all_entries = load_all_entries()
    candidates, error = _session_or_error(session, all_entries)
    if error:
        return error
    snapshot = load_grind_snapshot(session)
    if snapshot is not None:
        return {
            "session": session,
            "source": "saved_grind_run",
            "generated_at": snapshot.get("generated_at"),
            "note_count": snapshot.get("note_count", len(candidates)),
            "note_ids": snapshot.get("note_ids", []),
            "insights": snapshot["insights"],
        }
    preview = design_insights(candidates, graph_data(candidates))
    return {
        "session": session,
        "source": "local_preview",
        "generated_at": None,
        "note_count": len(candidates),
        "notice": "No saved GPT-5.6 GRIND run exists yet. Open this active session in SKATE and run The GRIND to create one.",
        "insights": preview,
    }


def search(query: str) -> dict[str, Any]:
    """Compatibility search tool for ChatGPT knowledge/research surfaces."""
    result = search_memory(query=query, top_k=10)
    if result.get("error"):
        return result
    return {
        "results": [
            {
                "id": item["memory_id"],
                "title": item["title"],
                "text": item["excerpt"],
                "url": item["uri"],
            }
            for item in result["results"]
        ],
        "metadata": {
            key: result[key]
            for key in (
                "retrieval_mode",
                "eligible_memory_count",
                "returned_memory_count",
                "estimated_full_context_tokens",
                "estimated_returned_excerpt_tokens",
                "estimated_context_reduction_percent",
            )
        },
    }


def fetch(memory_id: str) -> dict[str, Any]:
    """Compatibility fetch tool for ChatGPT knowledge/research surfaces."""
    result = get_memory_object(memory_id)
    if result.get("error"):
        return result
    return {
        "id": result["memory_id"],
        "title": result["title"],
        "text": result["body"],
        "url": result["uri"],
        "metadata": {key: value for key, value in result.items() if key not in {"body", "excerpt"}},
    }
