#!/usr/bin/env python3
"""
SKATE — add_entry.py

Interactive CLI to add a new memory object to the SKATE vault.
Walks you through frontmatter (title, type, tags, themes, session,
relationships), drops a file in conversations/notes/, and updates INDEX.md.

Usage:
    python add_entry.py
    python add_entry.py --title "My conversation" --type observation

No external dependencies. Pure Python stdlib.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

SKATE_ROOT = Path(__file__).resolve().parent.parent
CONVERSATIONS = SKATE_ROOT / "conversations"
NOTES_FOLDER = CONVERSATIONS / "notes"
TEMPLATES = SKATE_ROOT / "templates"
INDEX_FILE = SKATE_ROOT / "INDEX.md"

# Memory object types (kept in sync with ui/skate_lib.py ENTRY_TYPES).
ENTRY_TYPES = [
    "note",
    "observation",
    "pain",
    "quote",
    "hypothesis",
    "decision",
    "recommendation",
    "action",
    "risk",
    "question",
    "opportunity",
    "solution",
    "insight",
    "process",
]

# Relationship types (kept in sync with ui/skate_lib.py RELATIONSHIP_TYPES).
RELATIONSHIP_TYPES = [
    "supports",
    "contradicts",
    "causes",
    "leads_to",
    "references",
    "similar_to",
]


def slugify(text: str) -> str:
    """Convert a string to a safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:80].strip("-")


def prompt(question: str, default: str = "") -> str:
    """Prompt with optional default."""
    if default:
        full = f"{question} [{default}]: "
    else:
        full = f"{question}: "
    response = input(full).strip()
    return response or default


def prompt_multiline(question: str) -> str:
    """Multi-line input. End with a line containing only 'END'."""
    print(f"{question} (end with a line containing 'END'):")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def parse_relationship_lines(value: str) -> list[dict]:
    """Parse 'type | target | note' lines into relationship dicts."""
    relationships = []
    for line in (value or "").splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        rel_type = (parts[0] if parts else "references").lower().replace("-", "_").replace(" ", "_")
        target = parts[1] if len(parts) > 1 else ""
        note = parts[2] if len(parts) > 2 else ""
        if rel_type not in RELATIONSHIP_TYPES or not target:
            continue
        relationships.append({"type": rel_type, "target": target, "note": note})
    return relationships


def _yaml_list(items: list[str]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


def build_frontmatter(data: dict) -> str:
    lines = [
        "---",
        f'title: "{data["title"]}"',
        f"date: {data['date']}",
        f'type: "{data["entry_type"]}"',
        f'session: "{data["session"]}"',
        f'session_label: "{data["session_label"]}"',
        f"tags: {_yaml_list(data['tags'])}",
        f"themes: {_yaml_list(data['themes'])}",
        'participants: ["Facilitator", "Agent"]',
        f'status: "{data["status"]}"',
        "related: []",
    ]
    if data["relationships"]:
        lines.append("relationships:")
        for rel in data["relationships"]:
            lines.append(f'  - type: "{rel["type"]}"')
            lines.append(f'    target: "{rel["target"]}"')
            lines.append(f'    note: "{rel["note"]}"')
    else:
        lines.append("relationships: []")
    lines.append(f'source: "{data["source"]}"')
    lines.append("---")
    return "\n".join(lines) + "\n"


def build_body(data: dict) -> str:
    return f"""
# {data['title']}

## Summary

{data['summary']}

## Key Insights

{data['key_insights'] if data['key_insights'] else '- (to be filled in)'}

## Decisions

{data['decisions'] if data['decisions'] else '- (to be filled in)'}

## Action Items

{data['action_items'] if data['action_items'] else '- (to be filled in)'}

## Open Questions

{data['open_questions'] if data['open_questions'] else '- (to be filled in)'}

## Full Context

{data['full_context'] if data['full_context'] else '(to be filled in)'}

## References

{data['references'] if data['references'] else '- (to be filled in)'}
"""


def interactive_collect(args: argparse.Namespace) -> dict:
    print("=" * 60)
    print("SKATE — New Entry")
    print("=" * 60)
    print()

    title = args.title or prompt("Title")
    if not title:
        print("ERROR: title is required")
        sys.exit(1)

    date = args.date or prompt(
        "Date (YYYY-MM-DD)", datetime.date.today().isoformat()
    )

    entry_type = (args.type or prompt(
        f"Object type ({', '.join(ENTRY_TYPES)})", "note"
    )).strip().lower()
    if entry_type not in ENTRY_TYPES:
        print(f"WARNING: unknown type '{entry_type}', using 'note'")
        entry_type = "note"

    tags_raw = args.tags or prompt("Tags (comma-separated)", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    themes_raw = args.themes or prompt("Themes (comma-separated)", "")
    themes = [t.strip() for t in themes_raw.split(",") if t.strip()]

    session_raw = args.session or prompt("Workshop / session slug (optional)", "")
    session = slugify(session_raw) if session_raw else ""
    session_label = session_raw.strip() if session_raw else ""

    print()
    print("Relationships link this note to existing notes.")
    print(f"One per line as: type | target-filename.md | optional note")
    print(f"Types: {', '.join(RELATIONSHIP_TYPES)}")
    relationships_raw = prompt_multiline("Relationships (optional)")
    relationships = parse_relationship_lines(relationships_raw)

    status = prompt("Status", "complete")
    source = prompt("Source", "Cowork conversation")

    summary = prompt("One-paragraph summary (the bottom line)", "")

    print()
    print("Optional sections — press Enter to skip, or fill in now.")
    print("For multi-line content, you'll be prompted with 'END' to finish.")
    print()

    skip_long = prompt("Skip long-form sections and just create stub? (y/n)", "n").lower().startswith("y")

    if not skip_long:
        key_insights = prompt_multiline("Key insights (bullet form)")
        decisions = prompt_multiline("Decisions")
        action_items = prompt_multiline("Action items")
        open_questions = prompt_multiline("Open questions")
        full_context = prompt_multiline("Full context")
        references = prompt_multiline("References")
    else:
        key_insights = decisions = action_items = open_questions = ""
        full_context = references = ""

    return {
        "title": title,
        "date": date,
        "entry_type": entry_type,
        "tags": tags,
        "themes": themes,
        "session": session,
        "session_label": session_label,
        "relationships": relationships,
        "status": status,
        "source": source,
        "summary": summary,
        "key_insights": key_insights,
        "decisions": decisions,
        "action_items": action_items,
        "open_questions": open_questions,
        "full_context": full_context,
        "references": references,
    }


def write_entry(data: dict) -> Path:
    folder = NOTES_FOLDER
    folder.mkdir(parents=True, exist_ok=True)

    slug = slugify(data["title"])
    filename = f"{data['date']}-{slug}.md"
    path = folder / filename

    if path.exists():
        print(f"WARNING: {path} already exists. Appending suffix.")
        suffix = 1
        while path.exists():
            path = folder / f"{data['date']}-{slug}-{suffix}.md"
            suffix += 1

    content = build_frontmatter(data) + build_body(data)
    path.write_text(content, encoding="utf-8")
    return path


def append_to_index(data: dict, entry_path: Path) -> None:
    """Append a row to INDEX.md's All entries table."""
    if not INDEX_FILE.exists():
        print(f"WARNING: {INDEX_FILE} not found, skipping index update")
        return

    rel_path = entry_path.relative_to(SKATE_ROOT).as_posix()
    session_display = data["session"] or "—"
    themes_display = ", ".join(data["themes"]) if data["themes"] else "—"

    new_row = (
        f"| {data['date']} | {data['entry_type']} | {data['title']} | "
        f"{session_display} | {themes_display} | [link]({rel_path}) |\n"
    )

    content = INDEX_FILE.read_text(encoding="utf-8")
    # Insert new row right after the header row of the All entries table.
    pattern = re.compile(
        r"(\|\s*Date\s*\|\s*Type\s*\|.+?\n\|---.+?\n)",
        re.MULTILINE,
    )
    if pattern.search(content):
        content = pattern.sub(lambda m: m.group(1) + new_row, content, count=1)
        INDEX_FILE.write_text(content, encoding="utf-8")
        print(f"  Updated {INDEX_FILE.name}")
    else:
        print(f"  Couldn't find table header in {INDEX_FILE.name} — run tools/regenerate_index.py instead")


def main():
    parser = argparse.ArgumentParser(
        description="Add a new memory object to SKATE"
    )
    parser.add_argument("--title", help="Entry title")
    parser.add_argument("--date", help="Entry date (YYYY-MM-DD)")
    parser.add_argument("--type", help=f"Object type ({', '.join(ENTRY_TYPES)})")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--themes", help="Comma-separated themes")
    parser.add_argument("--session", help="Workshop / session slug")
    args = parser.parse_args()

    data = interactive_collect(args)

    print()
    print("=" * 60)
    print("Preview")
    print("=" * 60)
    print(f"  Title:      {data['title']}")
    print(f"  Date:       {data['date']}")
    print(f"  Type:       {data['entry_type']}")
    print(f"  Tags:       {', '.join(data['tags']) or '(none)'}")
    print(f"  Themes:     {', '.join(data['themes']) or '(none)'}")
    print(f"  Session:    {data['session'] or '(none)'}")
    print(f"  Links:      {len(data['relationships'])} relationship(s)")
    print(f"  Folder:     {NOTES_FOLDER.relative_to(SKATE_ROOT)}")
    print()
    confirm = prompt("Write entry? (y/n)", "y").lower()
    if not confirm.startswith("y"):
        print("Aborted.")
        sys.exit(0)

    path = write_entry(data)
    print(f"  Created: {path}")
    append_to_index(data, path)
    print()
    print("Done.")


if __name__ == "__main__":
    main()
