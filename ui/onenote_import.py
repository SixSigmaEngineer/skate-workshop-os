"""
onenote_import.py — convert exported OneNote content into SKATE-ready notes.

This module is intentionally dependency-light. Markdown, text, HTML, and Word
(.docx) are parsed with the Python standard library only, so the import works on
a fresh SKATE install with no extra pip packages. PDF is supported *if* the
optional `pypdf` package is present; otherwise PDFs are reported as skipped with
a clear reason.

Mapping (matches SKATE's own structure):
    OneNote Notebook  ->  SKATE session
    OneNote page/file ->  SKATE note

The module only *parses and plans*. Writing notes into the vault (frontmatter,
folders, session README) is done by the caller (app.py) so all vault conventions
stay in one place.
"""

from __future__ import annotations

import html as _html
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

# Extensions we know how to turn into Markdown.
TEXT_EXT = {".md", ".markdown", ".txt"}
HTML_EXT = {".html", ".htm"}
DOCX_EXT = {".docx"}
PDF_EXT = {".pdf"}
SUPPORTED_EXT = TEXT_EXT | HTML_EXT | DOCX_EXT | PDF_EXT

# OneNote's own binary export. We cannot parse it without OneNote itself.
UNSUPPORTED_EXT = {".one", ".onepkg", ".onetoc2"}

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def slugify(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "untitled"


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        m = re.match(r"^#{1,3}\s+(.*\S)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _title_from(markdown: str, fallback: str) -> str:
    heading = _first_heading(markdown)
    if heading:
        return heading
    # else first non-empty line, trimmed
    for line in markdown.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:120]
    return fallback


# --------------------------------------------------------------------------- #
# HTML -> Markdown (stdlib only, deliberately simple)
# --------------------------------------------------------------------------- #
class _MarkdownHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._list_stack: list[str] = []
        self._href: str | None = None
        self._skip_depth = 0  # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.out.append("\n\n" + "#" * level + " ")
        elif tag == "p" or tag == "div":
            self.out.append("\n\n")
        elif tag == "br":
            self.out.append("  \n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "ul":
            self._list_stack.append("ul")
            self.out.append("\n")
        elif tag == "ol":
            self._list_stack.append("ol")
            self.out.append("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self._list_stack) - 1)
            bullet = "1. " if (self._list_stack[-1:] == ["ol"]) else "- "
            self.out.append("\n" + indent + bullet)
        elif tag == "a":
            self._href = attrs.get("href")
            self.out.append("[")
        elif tag in ("tr",):
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self.out.append("\n")
        elif tag == "a":
            if self._href:
                self.out.append(f"]({self._href})")
            else:
                self.out.append("]")
            self._href = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div"):
            self.out.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        self.out.append(data)

    def text(self) -> str:
        raw = "".join(self.out)
        raw = _html.unescape(raw)
        # collapse 3+ newlines, trim trailing spaces per line
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip() + "\n"


def html_to_markdown(html_str: str) -> str:
    parser = _MarkdownHTMLParser()
    parser.feed(html_str)
    parser.close()
    return parser.text()


# --------------------------------------------------------------------------- #
# DOCX -> Markdown blocks (stdlib zipfile + xml)
# --------------------------------------------------------------------------- #
def _docx_paragraphs(path: Path) -> list[tuple[str, str]]:
    """Return [(style, text), ...] for each paragraph in a .docx.

    style is one of: 'h1','h2','h3','title','li','p'.
    """
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        try:
            xml_bytes = zf.read("word/document.xml")
        except KeyError:
            return []
    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_W_NS}body")
    if body is None:
        return []

    paragraphs: list[tuple[str, str]] = []
    for p in body.iter(f"{_W_NS}p"):
        # gather run text
        text_parts: list[str] = []
        for t in p.iter(f"{_W_NS}t"):
            text_parts.append(t.text or "")
        text = "".join(text_parts).strip()

        # style
        style = "p"
        pPr = p.find(f"{_W_NS}pPr")
        if pPr is not None:
            pStyle = pPr.find(f"{_W_NS}pStyle")
            if pStyle is not None:
                val = (pStyle.get(f"{_W_NS}val") or "").lower()
                if val in ("title",):
                    style = "title"
                elif val in ("heading1", "heading 1"):
                    style = "h1"
                elif val in ("heading2", "heading 2"):
                    style = "h2"
                elif val in ("heading3", "heading 3"):
                    style = "h3"
            if pPr.find(f"{_W_NS}numPr") is not None and style == "p":
                style = "li"
        if not text:
            continue
        paragraphs.append((style, text))
    return paragraphs


def _blocks_to_markdown(blocks: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for style, text in blocks:
        if style == "title":
            lines.append(f"# {text}")
        elif style == "h1":
            lines.append(f"# {text}")
        elif style == "h2":
            lines.append(f"## {text}")
        elif style == "h3":
            lines.append(f"### {text}")
        elif style == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
        lines.append("")
    md = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


# --------------------------------------------------------------------------- #
# PDF -> text (optional dependency)
# --------------------------------------------------------------------------- #
def pdf_to_markdown(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "PDF import needs the optional 'pypdf' package. Install it with "
            "`pip install pypdf`, or export from OneNote to Word (.docx) instead."
        ) from exc
    reader = PdfReader(str(path))
    chunks = []
    for page in reader.pages:
        chunks.append((page.extract_text() or "").strip())
    text = "\n\n".join(c for c in chunks if c)
    return text.strip() + "\n"


# --------------------------------------------------------------------------- #
# File -> one or more notes
# --------------------------------------------------------------------------- #
def extract_notes(path: Path, split_pages: bool = True) -> list[dict]:
    """Convert a single exported file into one or more note dicts.

    Returns: [{ "title": str, "body": str }]
    Splitting: for .docx/.html, when split_pages is True, the file is broken
    into one note per top-level heading (OneNote page titles export as headings).
    """
    ext = path.suffix.lower()
    stem = path.stem

    if ext in TEXT_EXT:
        body = path.read_text(encoding="utf-8", errors="replace")
        return _maybe_split(body, stem, split_pages)

    if ext in HTML_EXT:
        body = html_to_markdown(path.read_text(encoding="utf-8", errors="replace"))
        return _maybe_split(body, stem, split_pages)

    if ext in DOCX_EXT:
        blocks = _docx_paragraphs(path)
        if not blocks:
            return [{"title": stem, "body": f"# {stem}\n\n_(empty document)_\n"}]
        if split_pages:
            return _split_blocks_by_heading(blocks, stem)
        return [{"title": _title_from(_blocks_to_markdown(blocks), stem),
                 "body": _blocks_to_markdown(blocks)}]

    if ext in PDF_EXT:
        body = pdf_to_markdown(path)  # may raise RuntimeError -> caller handles
        if not body.lstrip().startswith("#"):
            body = f"# {stem}\n\n{body}"
        return [{"title": _title_from(body, stem), "body": body}]

    raise RuntimeError(f"Unsupported file type: {ext}")


def _maybe_split(markdown: str, stem: str, split_pages: bool) -> list[dict]:
    if not split_pages:
        return [{"title": _title_from(markdown, stem), "body": _ensure_title(markdown, stem)}]
    parts = _split_markdown_by_h1(markdown)
    if len(parts) <= 1:
        return [{"title": _title_from(markdown, stem), "body": _ensure_title(markdown, stem)}]
    notes = []
    for title, body in parts:
        notes.append({"title": title or stem, "body": _ensure_title(body, title or stem)})
    return notes


def _ensure_title(markdown: str, title: str) -> str:
    if _first_heading(markdown):
        return markdown.strip() + "\n"
    return f"# {title}\n\n{markdown.strip()}\n"


def _split_markdown_by_h1(markdown: str) -> list[tuple[str, str]]:
    """Split markdown into (title, body) chunks at each level-1 heading."""
    lines = markdown.splitlines()
    chunks: list[tuple[str, list[str]]] = []
    current_title = None
    current: list[str] = []
    for line in lines:
        m = re.match(r"^#\s+(.*\S)\s*$", line)
        if m:
            if current_title is not None or any(s.strip() for s in current):
                chunks.append((current_title, current))
            current_title = m.group(1).strip()
            current = [line]
        else:
            current.append(line)
    if current_title is not None or any(s.strip() for s in current):
        chunks.append((current_title, current))
    return [(t or "", "\n".join(b).strip()) for t, b in chunks if any(s.strip() for s in b)]


def _split_blocks_by_heading(blocks: list[tuple[str, str]], stem: str) -> list[dict]:
    """Split docx blocks into notes at each title/h1."""
    notes: list[dict] = []
    cur_title = None
    cur: list[tuple[str, str]] = []

    def flush():
        if cur:
            title = cur_title or stem
            md = _blocks_to_markdown(cur)
            md = _ensure_title(md, title)
            notes.append({"title": title, "body": md})

    for style, text in blocks:
        if style in ("title", "h1"):
            flush()
            cur_title = text
            cur = [(style, text)]
        else:
            cur.append((style, text))
    flush()
    if not notes:
        notes.append({"title": stem, "body": f"# {stem}\n"})
    return notes


# --------------------------------------------------------------------------- #
# Discovery + planning
# --------------------------------------------------------------------------- #
def _discover(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    files = []
    for p in sorted(source.rglob("*")):
        if p.is_file() and p.suffix.lower() in (SUPPORTED_EXT | UNSUPPORTED_EXT):
            files.append(p)
    return files


def _notebook_for(file_path: Path, source: Path, mode: str, default_name: str) -> str:
    if mode == "single" or source.is_file():
        return default_name
    try:
        rel = file_path.relative_to(source)
    except ValueError:
        return default_name
    parts = rel.parts
    if len(parts) >= 2:
        return parts[0]  # top-level folder = Notebook
    return default_name  # file sat directly in the source root


def build_plan(
    source_path: str,
    mode: str = "by_folder",
    session_name: str = "OneNote Import",
    split_pages: bool = True,
    include_bodies: bool = False,
) -> dict:
    """Plan (and optionally materialize bodies for) a OneNote import.

    mode: "by_folder" -> each top-level subfolder is a Notebook/session.
          "single"    -> everything lands in one session (session_name).
    """
    source = Path(source_path).expanduser()
    result: dict = {
        "source": str(source),
        "ok": False,
        "error": None,
        "mode": mode,
        "split_pages": split_pages,
        "notebooks": [],
        "total_files": 0,
        "total_notes": 0,
        "skipped": [],
        "warnings": [],
    }
    if not source.exists():
        result["error"] = f"Path not found: {source}"
        return result

    files = _discover(source)
    if not files:
        result["error"] = (
            "No importable files found. Export your OneNote to Word (.docx), "
            "Markdown (.md), HTML, or PDF first, then point SKATE at that folder."
        )
        return result

    default_name = (session_name or "OneNote Import").strip() or "OneNote Import"
    notebooks: dict[str, dict] = {}

    for fp in files:
        ext = fp.suffix.lower()
        if ext in UNSUPPORTED_EXT:
            result["skipped"].append({
                "file": fp.name,
                "reason": "OneNote's own .one format can't be read directly. "
                          "Open it in OneNote and Export to Word or Markdown.",
            })
            continue
        result["total_files"] += 1
        nb_name = _notebook_for(fp, source, mode, default_name)
        nb = notebooks.setdefault(nb_name, {
            "name": nb_name,
            "session_slug": slugify(nb_name),
            "notes": [],
        })
        try:
            notes = extract_notes(fp, split_pages=split_pages)
        except Exception as exc:
            result["skipped"].append({"file": fp.name, "reason": str(exc)})
            continue
        for note in notes:
            entry = {
                "title": note["title"],
                "source_file": fp.name,
                "ext": ext,
                "char_count": len(note["body"]),
            }
            if include_bodies:
                entry["body"] = note["body"]
            nb["notes"].append(entry)
            result["total_notes"] += 1

    # stable order: notebook name asc
    result["notebooks"] = [notebooks[k] for k in sorted(notebooks)]
    result["ok"] = result["total_notes"] > 0 or bool(result["skipped"])
    if result["total_notes"] == 0 and not result["error"]:
        result["error"] = "Found files, but none could be converted. See skipped list."
    return result
