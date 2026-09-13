"""
SKATE UI — local web app for reading the SKATE vault.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:8765 in your browser.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import os
import shutil
import sys
import threading
import time
import uuid
import webbrowser
import wave
import zipfile
import hashlib
from calendar import monthrange
from io import BytesIO
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError
from xml.sax.saxutils import escape as xml_escape

import frontmatter
import markdown

import embeddings
import note_quality
import ui_themes
import vault_trash
from audio_uploads import receive_recording, UploadProblem, audio_sections
import asyncio

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from skate_lib import (
    CONVERSATIONS,
    PAIN_KEYWORDS,
    CONSULTING_THEMES,
    ENTRY_TYPES,
    RELATIONSHIP_TYPES,
    SESSIONS,
    SKATE_ROOT,
    capture_markers,
    design_insights,
    filter_entries,
    find_entry_by_id,
    graph_data,
    save_grind_snapshot,
    load_all_entries,
    search_entries,
    session_stats,
    theme_stats,
    vault_diagnostics,
)
from onenote_import import build_plan as _onenote_build_plan

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if (HERE / "ui" / "templates").exists():
    HERE = HERE / "ui"
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
STATIC_DIR = HERE / "static"
SETTINGS_PATH = SKATE_ROOT / "settings.json"
WORKSHOP_KNOWLEDGE_DIR = SKATE_ROOT / "workshop-knowledge-documents"
TRANSCRIPTION_RUN_LOCK = threading.Lock()
TRANSCRIPTION_JOBS: dict[str, dict] = {}
TRANSCRIPTION_JOBS_LOCK = threading.Lock()
WHISPER_PROGRESS_LOCK = threading.Lock()
WHISPER_MODEL_LOCK = threading.Lock()
WHISPER_MODEL_CACHE: dict[str, object] = {"name": None, "model": None}

# Local transcription only ever fetches PUBLIC Whisper models (a one-time
# model-weights download; audio never leaves this computer). Never send a
# HuggingFace credential: a stale local login otherwise causes 401
# "Repository Not Found" errors on public models.
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
for _hf_var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
    os.environ.pop(_hf_var, None)
APP_SHOW_REQUESTED = threading.Event()
_SINGLE_INSTANCE_MUTEX = None

OPENAI_MODEL_OPTIONS = [
    {"id": "gpt-5.6", "label": "GPT-5.6 Sol — frontier"},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra — balanced"},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna — efficient"},
]
ANTHROPIC_MODEL_OPTIONS = [
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 — balanced"},
    {"id": "claude-opus-5", "label": "Claude Opus 5 — deep reasoning"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 — fast"},
]
MODEL_OPTIONS = {"openai": OPENAI_MODEL_OPTIONS, "anthropic": ANTHROPIC_MODEL_OPTIONS}

# LLM provider selection. "none" runs SKATE with deterministic local
# synthesis only; "lmstudio" talks to a local OpenAI-compatible server.
LLM_PROVIDERS = ("none", "lmstudio", "openai", "anthropic", "openrouter")
LLM_PROVIDER_LABELS = {
    "none": "No AI — local synthesis only",
    "lmstudio": "LM Studio — local LLM",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "openrouter": "OpenRouter",
}

DEFAULT_SETTINGS = {
    "provider": "openai",
    "model": "gpt-5.6",
    "spotter_model": "",
    "spotter_anthropic_model": "",
    "spotter_reasoning_effort": "low",
    "reasoning_effort": "medium",
    "api_keys": {"openai": "", "anthropic": "", "openrouter": "", "elevenlabs": ""},
    "transcription_model": "base",
    "openai_base_url": "https://api.openai.com/v1",
    "anthropic_model": "claude-sonnet-5",
    "openrouter_model": "anthropic/claude-sonnet-5",
    "lmstudio_base_url": "http://127.0.0.1:1234/v1",
    "lmstudio_model": "",
    "max_tokens": 1920,
    "spotter_name": "Spotter",
    "spotter_subtitle": "Workshop coach",
    "spotter_persona": """You are Spotter, an expert facilitation co-pilot for consultants and workshop teams. You support facilitators and project teams live during workshops.

You listen for the moments that matter - pain points, contradictions, root causes, decisions, and opportunities - and turn them into structured, typed notes before they evaporate. Ground your coaching in Lean and design-thinking practice (5 Whys, How-Might-We framing, gemba observation), keep spoken responses short and workshop-friendly, and always connect findings back to measurable outcomes for the client.""",
    "spotter_methodology": """Use the right tool for the moment:
- Process analysis and Gemba: observe how work actually happens, identify handoffs, queues, rework, decision points, system friction, hidden work, and pain points.
- Lean Six Sigma is the backbone: DMAIC, Gemba/process walk, the 8 wastes using DOWNTIME, VA/NVA/NVAR, current- vs future-state mapping, 5 Whys, try-storming countermeasures, and control plans.
- Kaizen / Rapid Improvement Events: plan, prepare, run the 2-5 day event, then follow up. Use a clear charter, case for change, and specific problem statement.
- Design Thinking and Human-Centered Design: inspiration, ideation, implementation; empathize, define, ideate, prototype, test; How Might We framing; test desirability, feasibility, and viability.
- DFSS and BDFSS: use data and real-world validation such as Gemba and VOC to drive innovation and improvement decisions, not opinion. Connect to ROI and business case when relevant.
- AI and automation: look for opportunities where AI assistants, workflow automation, data integration, knowledge graphs, dashboards, decision support, or agentic handoffs can reduce waste, improve quality, increase speed, or make ROI measurable.""",
    "spotter_style": """Operator-grade. Lead with the bottom line, then 2-3 supporting points. Keep answers skimmable and direct. No filler. When the user is capturing a pain point, idea, waste, VOC quote, risk, recommendation, or decision, reflect it back in clean structured form and ask at most one sharp follow-up. When asked to facilitate, be decisive and offer the next concrete step.""",
    "microphone": "system-default",
    "microphone_label": "",
    "speech_to_text_provider": "openai",
    "text_to_speech_provider": "openai",
    "speak_responses_aloud": True,
    "openai_realtime_model": "gpt-realtime-mini",
    "openai_realtime_transcription_model": "gpt-realtime-whisper",
    "openai_realtime_transcription_delay": "low",
    "openai_realtime_voice": "marin",
    "openai_batch_transcription_model": "gpt-4o-mini-transcribe",
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",
    "elevenlabs_tts_model": "eleven_flash_v2_5",
    "elevenlabs_stt_model": "scribe_v2",
    "streamdeck_port": 3030,
    "streamdeck_auto_send": True,
}

WHISPER_MODELS = [
    {"id": "tiny", "label": "Tiny - fastest, roughest"},
    {"id": "base", "label": "Base - balanced default"},
    {"id": "small", "label": "Small - better, slower"},
    {"id": "medium", "label": "Medium - strong, much slower"},
    {"id": "turbo", "label": "Turbo - fast high-quality model"},
]

STATUS_OPTIONS = ["active", "inactive"]
SESSION_STATUS_OPTIONS = {"active", "inactive"}
SOURCE_OPTIONS = ["manual note", "workshop capture", "voice transcript", "audio upload", "spotter", "grind capture", "imported note"]
LINEUP_CADENCES = {
    "once": "One time",
    "daily": "Daily",
    "weekdays": "Weekdays",
    "weekly": "Weekly",
    "monthly": "Monthly",
}

SPOTTER_MODES = [
    {
        "id": "observe",
        "label": "Observe",
        "wake_label": "Observe",
        "deck_icon": "prompt-observe.png",
        "entry_type": "observation",
        "prompt": "Wake up as an IDEO-style workshop observer. Listen for what people do, say, feel, avoid, repeat, and work around. Use session notes when available.",
    },
    {
        "id": "frame-challenge",
        "label": "Frame Challenge",
        "wake_label": "Frame",
        "entry_type": "pain",
        "deck_icon": "prompt-frame-challenge.png",
        "prompt": "Wake up as a design thinking problem-framing coach. Turn the capture and relevant session notes into a clear challenge, affected users, constraints, evidence, and assumptions.",
    },
    {
        "id": "hmw",
        "label": "How Might We",
        "wake_label": "HMW",
        "entry_type": "question",
        "deck_icon": "prompt-hmw.png",
        "prompt": "Wake up as a design thinking facilitator. Convert the capture and relevant session notes into strong How Might We prompts that are broad enough for ideation and specific enough for action.",
    },
    {
        "id": "five-whys",
        "label": "5 Whys",
        "wake_label": "5 Whys",
        "entry_type": "insight",
        "deck_icon": "prompt-five-whys.png",
        "prompt": "Wake up as a root-cause coach. Facilitate a concise 5 Whys chain using the capture and session notes. Separate observed symptoms from plausible root causes.",
    },
    {
        "id": "kaizen",
        "label": "Kaizen Event",
        "wake_label": "Kaizen",
        "entry_type": "process",
        "deck_icon": "prompt-kaizen.png",
        "prompt": "Wake up as a Kaizen event coach. Look for current state, waste, standard work gaps, quick wins, owners, daily management signals, and the next experiment.",
    },
    {
        "id": "process-map",
        "label": "Process Map",
        "wake_label": "Map Flow",
        "entry_type": "process",
        "deck_icon": "prompt-process-map.png",
        "prompt": "Wake up as a process improvement coach. Map the flow implied by the capture and session notes: trigger, handoffs, queues, rework loops, systems, decisions, and outputs.",
    },
    {
        "id": "find-waste",
        "label": "Find Waste",
        "wake_label": "Waste",
        "entry_type": "pain",
        "deck_icon": "prompt-find-waste.png",
        "prompt": "Wake up as a Lean coach. Listen for process waste, delay, defects, overprocessing, motion, inventory, waiting, handoff friction, and avoidable cognitive load.",
    },
    {
        "id": "synthesize-notes",
        "label": "Synthesize Notes",
        "wake_label": "Synthesize",
        "entry_type": "insight",
        "deck_icon": "prompt-synthesize-notes.png",
        "prompt": "Wake up as a workshop synthesis partner. Read the applicable session notes, connect patterns, identify tensions, and summarize what the team should notice now.",
    },
    {
        "id": "next-experiment",
        "label": "Next Experiment",
        "wake_label": "Experiment",
        "entry_type": "recommendation",
        "deck_icon": "prompt-next-experiment.png",
        "prompt": "Wake up as a practical experimentation coach. Turn the capture and notes into the smallest useful test, owner, metric, learning goal, and next decision.",
    },
    {
        "id": "executive-readout",
        "label": "Executive Readout",
        "wake_label": "Readout",
        "entry_type": "insight",
        "deck_icon": "prompt-executive-readout.png",
        "prompt": "Wake up as an executive synthesis coach. Turn the capture and applicable session notes into executive-ready insight, recommendation, decision needed, and action path.",
    },
    {
        "id": "ask",
        "label": "Ask Spotter",
        "wake_label": "Ask",
        "entry_type": "observation",
        "deck_icon": "prompt-ask-spotter.png",
        "prompt": "Wake up as Spotter, a workshop coach using IDEO-style design thinking, Kaizen events, Lean process improvement, HFE, and transformation consulting. Use notes if a session is active.",
    },
]

# pythonw.exe has no attached console. Keep occasional status/warning prints
# from crashing when SKATE is launched as a background tray app.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

MD = markdown.Markdown(
    extensions=["fenced_code", "tables", "toc", "codehilite", "sane_lists"]
)

CAPTURE_MARKER_LABELS = {
    "P": "Pain",
    "O": "Observation",
    "A": "Action Item",
    "Q": "Question",
    "S": "Solution",
    "R": "Recommendation",
    "I": "Insight",
}


_MARKER_WORD_CODES = {
    "pain": "P",
    "observation": "O",
    "action": "A",
    "action item": "A",
    "question": "Q",
    "open question": "Q",
    "solution": "S",
    "recommendation": "R",
    "insight": "I",
}


def _decorate_capture_markers(body_html: str) -> str:
    """Apply the capture-button color language to rendered note bullets.

    Both signal syntaxes are decorated: compact markers (``#P:``) and the
    readable labels the quick-capture buttons insert (``Pain:``).
    """
    def replace_marker(match: re.Match) -> str:
        hash_code, word = match.group(1), match.group(2)
        if hash_code:
            code = hash_code.upper()
            shown = f"#{code}:"
        else:
            code = _MARKER_WORD_CODES[word.lower()]
            shown = f"{word}:"
        label = CAPTURE_MARKER_LABELS[code]
        return (
            f'<li class="capture-line capture-line-{code.lower()}">'
            f'<span class="capture-marker capture-marker-{code.lower()}" title="{label}">{shown}</span> '
        )

    words = "|".join(sorted(_MARKER_WORD_CODES, key=len, reverse=True))
    return re.sub(
        rf"<li>\s*(?:#([POAQRSI]):|({words}):)\s*",
        replace_marker,
        body_html,
        flags=re.I,
    )

app = FastAPI(title="SKATE")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _load_settings() -> dict:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update({k: v for k, v in loaded.items() if k != "api_keys"})
                if isinstance(loaded.get("api_keys"), dict):
                    for provider in settings["api_keys"]:
                        if provider in loaded["api_keys"]:
                            settings["api_keys"][provider] = loaded["api_keys"][provider]
        except (OSError, json.JSONDecodeError):
            pass
    for deprecated_key in (
        "spotter_provider",
        "grind_provider",
        "grind_model",
        "grind_reasoning_effort",
        "use_ai_synthesis",
    ):
        settings.pop(deprecated_key, None)
    # Automatically neutralize the legacy company-specific Spotter identity
    # in older settings files. Spotter must remain reusable across clients,
    # organizations, industries, and community workshops.
    legacy_subtitle = str(settings.get("spotter_subtitle", "")).strip().lower()
    legacy_persona = str(settings.get("spotter_persona", "")).strip().lower()
    has_branded_profile = all(
        marker in legacy_persona
        for marker in ("tagline:", "service areas:", "accelerators include")
    )
    if legacy_subtitle.startswith("workshop coach - ") or has_branded_profile:
        settings["spotter_subtitle"] = DEFAULT_SETTINGS["spotter_subtitle"]
        settings["spotter_persona"] = DEFAULT_SETTINGS["spotter_persona"]
        try:
            SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError:
            pass
    if settings.get("provider") not in LLM_PROVIDERS:
        settings["provider"] = "openai"
    valid_models = {m["id"] for m in OPENAI_MODEL_OPTIONS}
    if settings.get("model") not in valid_models:
        settings["model"] = "gpt-5.6"
    valid_anthropic = {m["id"] for m in ANTHROPIC_MODEL_OPTIONS}
    if settings.get("anthropic_model") not in valid_anthropic:
        settings["anthropic_model"] = "claude-sonnet-5"
    if settings.get("spotter_anthropic_model") not in valid_anthropic:
        settings["spotter_anthropic_model"] = ""
    settings["openrouter_model"] = str(settings.get("openrouter_model") or "").strip() or DEFAULT_SETTINGS["openrouter_model"]
    settings["lmstudio_base_url"] = str(settings.get("lmstudio_base_url") or "").strip() or DEFAULT_SETTINGS["lmstudio_base_url"]
    settings["lmstudio_model"] = str(settings.get("lmstudio_model") or "").strip()
    reasoning_efforts = {"none", "low", "medium", "high", "xhigh", "max"}
    for key, fallback in (
        ("reasoning_effort", "medium"),
        ("spotter_reasoning_effort", "low"),
    ):
        if settings.get(key) not in reasoning_efforts:
            settings[key] = fallback
    whisper_models = {m["id"] for m in WHISPER_MODELS}
    if settings.get("transcription_model") not in whisper_models:
        settings["transcription_model"] = "base"
    if settings.get("speech_to_text_provider") not in {"local", "openai", "elevenlabs"}:
        settings["speech_to_text_provider"] = "openai"
    if settings.get("elevenlabs_stt_model") not in {"scribe_v2", "scribe_v1"}:
        settings["elevenlabs_stt_model"] = "scribe_v2"
    try:
        settings["max_tokens"] = max(128, min(16000, int(settings.get("max_tokens", 1920))))
    except (TypeError, ValueError):
        settings["max_tokens"] = 1920
    try:
        settings["streamdeck_port"] = max(1, min(65535, int(settings.get("streamdeck_port", 3030))))
    except (TypeError, ValueError):
        settings["streamdeck_port"] = 3030
    try:
        settings["recording_upload_limit_mb"] = max(250, min(4096, int(settings.get("recording_upload_limit_mb", 2048))))
    except (TypeError, ValueError):
        settings["recording_upload_limit_mb"] = 2048
    if settings.get("ui_theme") not in {row[0] for row in ui_themes.PALETTES}:
        settings["ui_theme"] = "default"
    return settings


def _audio_upload_limit() -> int:
    return int(_load_settings().get("recording_upload_limit_mb", 2048)) * 1024 * 1024


def _save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _public_settings(settings: dict) -> dict:
    public = dict(settings)
    public["api_key_present"] = {
        provider: bool(settings.get("api_keys", {}).get(provider))
        for provider in ("openai", "anthropic", "openrouter", "elevenlabs")
    }
    public.pop("api_keys", None)
    return public


def _llm_available(settings: dict) -> bool:
    """True when the selected provider can serve AI synthesis."""
    provider = settings.get("provider", "openai")
    if provider == "none":
        return False
    if provider == "lmstudio":
        return True  # local server; reachability is checked at call time
    return bool(settings.get("api_keys", {}).get(provider))


def _llm_unavailable_reason(settings: dict) -> str:
    """Human-readable reason used when SKATE falls back to local synthesis."""
    provider = settings.get("provider", "openai")
    if provider == "none":
        return "AI synthesis is turned off in Settings"
    label = LLM_PROVIDER_LABELS.get(provider, provider)
    return f"No {label} API key is saved"


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serve favicon at the root path browsers expect."""
    ico = STATIC_DIR / "favicon.ico"
    if ico.exists():
        return FileResponse(ico)
    png = STATIC_DIR / "favicon.png"
    if png.exists():
        return FileResponse(png)
    return Response(status_code=204)


@app.post("/api/app/show", include_in_schema=False)
def request_app_window():
    """Ask the existing desktop process to restore its hidden SKATE window."""
    APP_SHOW_REQUESTED.set()
    return {"ok": True}


def _sidebar_context() -> dict:
    """Common context for the sidebar (sessions, themes, entry types)."""
    entries = load_all_entries()
    settings = _load_settings()
    themes = ui_themes.catalog(SKATE_ROOT / "theme-boards", STATIC_DIR / "skateboards")
    current = next(row for row in themes if row["id"] == settings["ui_theme"])
    return {
        "ui_themes": themes, "ui_theme": current, "theme_boards_path": str(SKATE_ROOT / "theme-boards"),
        "sessions": session_stats(entries),
        "themes": theme_stats(entries),
        "entry_types": ENTRY_TYPES,
        "consulting_themes": CONSULTING_THEMES,
        "relationship_types": RELATIONSHIP_TYPES,
        "spotter_modes": SPOTTER_MODES,
        "total_entries": len(entries),
        "logo_exists": (STATIC_DIR / "logo.png").exists(),
        "vault_path": str(SKATE_ROOT),
        "settings": _public_settings(settings),
    }


# Notes sent to the model in one synthesis pass. Anything beyond this is
# dropped, so the UI says so rather than silently narrowing the session.
MAX_SYNTHESIS_NOTES = 40

# Total note text sent for synthesis, in characters (~9k tokens). Deliberately
# bounded rather than "send everything": long contexts measurably reduce recall
# well before a window is full, so a small relevant payload beats a large one.
SYNTHESIS_BODY_BUDGET = 36_000

# Every note gets at least this much before any note gets more, so a single
# long transcript cannot starve twelve short notes.
SYNTHESIS_BODY_FLOOR = 600

# Markers per type per note. A marker-heavy note used to spend the whole
# budget on signals and leave no room for the prose around them.
MAX_MARKERS_PER_TYPE = 12


def _allocate_body_budget(lengths: list[int]) -> list[int]:
    """Share the body budget across notes by what each actually needs.

    Water-filling: every note is guaranteed a floor, then whatever is left is
    handed out in even rounds to the notes still wanting more. Short notes
    take only what they use and release the rest, so a session of twelve brief
    notes plus one 90-minute transcript gives the transcript the surplus
    instead of truncating everything to an identical arbitrary width.
    """
    if not lengths:
        return []
    budget = max(SYNTHESIS_BODY_BUDGET, SYNTHESIS_BODY_FLOOR * len(lengths))
    limits = [min(length, SYNTHESIS_BODY_FLOOR) for length in lengths]
    remaining = budget - sum(limits)
    while remaining > 0:
        hungry = [i for i, length in enumerate(lengths) if length > limits[i]]
        if not hungry:
            break
        share = max(1, remaining // len(hungry))
        moved = False
        for i in hungry:
            give = min(share, lengths[i] - limits[i], remaining)
            if give <= 0:
                continue
            limits[i] += give
            remaining -= give
            moved = True
            if remaining <= 0:
                break
        if not moved:
            break
    return limits


# Marks elided text inside a selected excerpt so the model knows content was
# skipped rather than assuming it saw the whole note.
BODY_GAP_MARK = "[...]"

_MARKER_LINE = re.compile(
    r"(?im)^\s*(?:[-*]\s+)?"
    r"(?:\\?#\s*[POAQSRI](?:\s*:|\s+)"
    r"|(?:Pain|Observation|Action(?:\s+Item)?|(?:Open\s+)?Question|Solution|Recommendation|Insight)\s*:)"
)


def _split_body_chunks(body: str, target: int = 800) -> list[str]:
    """Split a body into scoreable chunks.

    Blank-line paragraphs first. Transcript-style walls of text (one block,
    line breaks per utterance, no blank lines) are regrouped into
    roughly target-sized runs of lines so selection can still reach into the
    middle and end of a long meeting instead of degenerating to "keep the
    opening"."""
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip("\n")
        if not para.strip():
            continue
        if len(para) <= max(target, 400):
            chunks.append(para)
            continue
        current = ""
        for line in para.splitlines():
            if current and len(current) + len(line) + 1 > target:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
    sliced: list[str] = []
    for chunk in chunks:
        if len(chunk) <= 2 * target:
            sliced.append(chunk)
        else:  # a single enormous line with no breaks at all
            sliced.extend(chunk[i : i + target] for i in range(0, len(chunk), target))
    return sliced


def _score_chunk(text: str, index: int, last_index: int) -> float:
    """Rank a chunk's claim on the body budget.

    Marked lines outrank everything - they are deliberate capture. The first
    and last chunks are kept next, because meeting notes state the problem at
    the top and record decisions and actions at the bottom, and tail-first
    truncation used to throw the bottom away. Everything else competes on the
    same pain vocabulary the local GRIND scores with."""
    score = 0.0
    if _MARKER_LINE.search(text):
        score += 100.0
    if index == 0 or index == last_index:
        score += 40.0
    lowered = text.lower()
    score += sum(4.0 for word in PAIN_KEYWORDS if word in lowered)
    if "?" in text:
        score += 2.0
    return score


def _select_body_excerpt(body: str, limit: int) -> tuple[str, bool]:
    """Fit a note into its budget by relevance instead of position.

    A body within budget passes through untouched. Otherwise chunks are chosen
    by _score_chunk, reassembled in document order, and gaps are marked with
    BODY_GAP_MARK. Never returns more than `limit` characters."""
    body = body.strip()
    if len(body) <= limit:
        return body, False
    chunks = _split_body_chunks(body)
    if len(chunks) <= 1:
        return body[:limit], True
    last = len(chunks) - 1
    order = sorted(
        range(len(chunks)),
        key=lambda i: (-_score_chunk(chunks[i], i, last), i),
    )
    overhead = len(BODY_GAP_MARK) + 4  # joiners plus a possible gap marker
    chosen: set[int] = set()
    used = 0
    for i in order:
        cost = len(chunks[i]) + overhead
        if used + cost > limit:
            continue
        chosen.add(i)
        used += cost
    if not chosen:
        return body[:limit], True
    parts: list[str] = []
    previous = None
    for i in sorted(chosen):
        if previous is None:
            if i != 0:
                parts.append(BODY_GAP_MARK)
        elif i != previous + 1:
            parts.append(BODY_GAP_MARK)
        parts.append(chunks[i])
        previous = i
    if last not in chosen:
        parts.append(BODY_GAP_MARK)
    return "\n\n".join(parts)[:limit], True


def _entry_payload(entries) -> list[dict]:
    """Build the note payload for AI synthesis.

    Sends the note body, not just the summary. `summary` is only the
    "## Summary" section or the first non-heading paragraph, so on a normal
    multi-paragraph facilitator note it can be a single opening line - the
    model never saw the paragraphs where the actual problem was described.

    The budget is shared by need rather than split evenly - see
    _allocate_body_budget - so one long transcript in a session of short notes
    keeps most of itself instead of every note being cut to the same width.

    `summary` is deliberately not sent: it is derived from the body, so
    including both shipped the opening paragraph twice and spent budget that
    is better given to the rest of the note.
    """
    scoped = entries[:MAX_SYNTHESIS_NOTES]
    bodies = []
    for entry in scoped:
        body = _normalize_newlines(entry.body or "").strip()
        reviewed = note_quality.screen(body, " ".join(entry.themes + entry.tags))
        bodies.append(reviewed["text"] if reviewed["excluded_count"] else body)
    limits = _allocate_body_budget([len(body) for body in bodies])
    payload = []
    for entry, body, limit in zip(scoped, bodies, limits):
        excerpt, truncated = _select_body_excerpt(body, limit)
        markers = {
            marker_type: texts[:MAX_MARKERS_PER_TYPE]
            for marker_type, texts in capture_markers(entry).items()
        }
        payload.append(
            {
                "title": entry.title,
                "date": entry.date,
                "type": entry.entry_type,
                "themes": entry.themes,
                "tags": entry.tags,
                "capture_markers": markers,
                "body": excerpt,
                "body_truncated": truncated,
            }
        )
    return payload


def _synthesis_prompt(entries, graph: dict) -> str:
    payload = {
        "entries": _entry_payload(entries),
        "graph_stats": graph.get("stats", {}),
    }
    return (
        note_quality.RELEVANCE_RULES + "\n"
        "You are helping synthesize a design-thinking workshop in SKATE. "
        "Treat explicit capture markers as the primary workshop evidence: "
        "#P pains and unmet needs; #O direct observations; #Q open questions and HMW seeds; "
        "#A owned actions or experiments; #S proposed solutions; #R recommendations; "
        "and #I synthesized insights. Do not flatten these categories or invent evidence. "
        "Each note also carries `body`: the note as the facilitator actually wrote it. "
        "Markers remain the primary evidence and should be preferred wherever they exist, "
        "but the body often describes a problem that nobody stopped to mark in the room - "
        "read it, and surface those too, attributing them to the note they came from. "
        "`body_truncated` true means the note exceeded its budget, so `body` is a relevance-selected excerpt and [...] marks skipped text. "
        "Use observations to support pains, insights to connect patterns, questions to frame HMW prompts, "
        "and solutions/recommendations/actions to create testable solution starters. "
        "Read the scoped notes and return ONLY valid JSON with this shape: "
        "{\"pains\":[{\"title\":\"\",\"summary\":\"\"}],"
        "\"hmw_prompts\":[{\"prompt\":\"\",\"source_title\":\"\"}],"
        "\"solutions\":[{\"title\":\"\",\"summary\":\"\"}]}. "
        "Prefer concrete operational pain points, concise HMW prompts, and testable solution starters. "
        "Use at most 10 pains, 10 HMW prompts, and 10 solutions.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("The model did not return JSON.")
    return json.loads(text[start : end + 1])


def _normalize_ai_insights(raw: dict, entries) -> dict:
    first_entry = entries[0] if entries else None
    fallback_url = f"/entry/{first_entry.file_id}" if first_entry else "#"

    pains = []
    for item in raw.get("pains", [])[:10]:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        summary = str(item.get("summary", "")).strip()
        pains.append(
            {
                "title": title,
                "summary": summary,
                "score": 0,
                "entry_type": "pain",
                "source_url": fallback_url,
                "session": "",
                "capture_title": f"Pain: {title}",
                "capture_summary": summary,
                "capture_body": f"#P: {title}\n\n{summary}",
            }
        )

    hmw_prompts = []
    for item in raw.get("hmw_prompts", [])[:10]:
        prompt = str(item.get("prompt", "")).strip()
        if not prompt:
            continue
        hmw_prompts.append(
            {
                "prompt": prompt,
                "source_title": str(item.get("source_title", "")).strip(),
                "capture_title": prompt[:90],
                "capture_summary": prompt,
                "capture_body": f"#Q: {prompt}",
            }
        )

    solutions = []
    for item in raw.get("solutions", [])[:10]:
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not title and not summary:
            continue
        solutions.append(
            {
                "title": title or "Solution starter",
                "summary": summary,
                "source_url": fallback_url,
                "capture_title": f"Solution: {title or 'Starter'}",
                "capture_summary": summary,
                "capture_body": f"#S: {title or 'Solution starter'}\n\n{summary}",
            }
        )

    return {"pains": pains, "hmw_prompts": hmw_prompts, "solutions": solutions}


class ModelHTTPError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = UrlRequest(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace").strip()
        except Exception:
            detail = ""
        if len(detail) > 600:
            detail = detail[:600] + "…"
        raise ModelHTTPError(e.code, f"API returned HTTP {e.code}: {detail or e.reason}") from e


def _post_multipart(url: str, headers: dict, fields: dict[str, str], files: dict[str, dict], timeout: int = 90) -> dict:
    boundary = f"----SKATE{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, file_info in files.items():
        filename = file_info.get("filename") or "recording.webm"
        content_type = file_info.get("content_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                file_info["content"],
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    request_headers = dict(headers)
    request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = UrlRequest(url, data=body, headers=request_headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _pcm16_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap mono 16-bit PCM returned by Realtime in a browser-playable WAV."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


async def _openai_realtime_speak(text: str, api_key: str, model: str, voice: str) -> bytes:
    """Generate one low-latency spoken Spotter turn with GPT-Realtime mini."""
    import websockets

    url = f"wss://api.openai.com/v1/realtime?model={model or 'gpt-realtime-mini'}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        connect = websockets.connect(url, additional_headers=headers, max_size=20 * 1024 * 1024)
    except TypeError:  # websockets < 14
        connect = websockets.connect(url, extra_headers=headers, max_size=20 * 1024 * 1024)
    chunks: list[bytes] = []
    async with connect as upstream:
        await upstream.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": model or "gpt-realtime-mini",
                "output_modalities": ["audio"],
                "audio": {
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": voice or "marin",
                    }
                },
                "instructions": "Speak the supplied text naturally and exactly. Do not add commentary.",
            },
        }))
        await upstream.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": f"Say exactly this:\n{text}"}],
            },
        }))
        await upstream.send(json.dumps({"type": "response.create", "response": {"output_modalities": ["audio"]}}))
        async for raw in upstream:
            event = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            if event.get("type") == "response.output_audio.delta" and event.get("delta"):
                chunks.append(base64.b64decode(event["delta"]))
            elif event.get("type") == "error":
                detail = event.get("error") or {}
                raise ValueError(detail.get("message") or "OpenAI Realtime returned an error.")
            elif event.get("type") == "response.done":
                break
    if not chunks:
        raise ValueError("OpenAI Realtime returned no audio.")
    return _pcm16_to_wav(b"".join(chunks))


def _elevenlabs_list_voices(api_key: str) -> list[dict]:
    """Return the account's available ElevenLabs voices as [{id, name, category}]."""
    request = UrlRequest(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": api_key},
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    voices = []
    for voice in data.get("voices", []):
        voice_id = voice.get("voice_id")
        if voice_id:
            voices.append({
                "id": voice_id,
                "name": str(voice.get("name", voice_id)),
                "category": str(voice.get("category", "")),
            })
    voices.sort(key=lambda v: v["name"].lower())
    return voices


def _elevenlabs_tts(text: str, api_key: str, voice_id: str, model_id: str) -> bytes:
    """Synthesize speech with the ElevenLabs text-to-speech API. Returns MP3 bytes."""
    body = json.dumps({"text": text, "model_id": model_id or "eleven_flash_v2_5"}).encode("utf-8")
    request = UrlRequest(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or '21m00Tcm4TlvDq8ikWAM'}",
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return response.read()


def _feature_settings(settings: dict, feature: str) -> dict:
    """Return settings with a feature-specific model and effort override.

    A feature (e.g. Spotter) can run a faster model than GRIND: the OpenAI
    override uses {feature}_model, the Anthropic override uses
    {feature}_anthropic_model. The reasoning override applies to every
    provider that supports one.
    """
    provider = settings.get("provider", "openai")
    model = str(settings.get(f"{feature}_model") or "").strip()
    anthropic_model = str(settings.get(f"{feature}_anthropic_model") or "").strip()
    reasoning_effort = str(settings.get(f"{feature}_reasoning_effort") or "").strip()
    if not model and not anthropic_model and not reasoning_effort:
        return settings
    eff = dict(settings)
    if model and provider == "openai":
        eff["model"] = model
    if anthropic_model and provider == "anthropic":
        eff["anthropic_model"] = anthropic_model
    if reasoning_effort:
        eff["reasoning_effort"] = reasoning_effort
    return eff


def _grind_settings(settings: dict) -> dict:
    """Use the configured General model and reasoning for GRIND."""
    return dict(settings)


def _active_model(settings: dict) -> str:
    """The model id in effect for the selected provider."""
    provider = settings.get("provider", "openai")
    if provider == "anthropic":
        return str(settings.get("anthropic_model") or "claude-sonnet-5")
    if provider == "openrouter":
        return str(settings.get("openrouter_model") or "").strip()
    if provider == "lmstudio":
        return str(settings.get("lmstudio_model") or "").strip()
    return str(settings.get("model") or "gpt-5.6")


def _chat_completions(base_url: str, headers: dict, model: str, prompt: str, max_out: int, reasoning_effort: str = "") -> str:
    """Call an OpenAI-compatible chat completions endpoint (OpenRouter, LM Studio)."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_out,
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    try:
        response = _post_json(f"{base_url}/chat/completions", headers, payload)
    except ValueError as exc:
        if isinstance(exc, ModelHTTPError) and exc.status_code not in {400, 422}:
            raise
        # Some models/servers reject the JSON-format or reasoning hints; retry plain.
        payload.pop("response_format", None)
        payload.pop("reasoning", None)
        response = _post_json(f"{base_url}/chat/completions", headers, payload)
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("The model returned no choices.")
    return str((choices[0].get("message") or {}).get("content") or "")


def _lmstudio_default_model(base_url: str) -> str:
    """Ask a local LM Studio server which model is loaded."""
    request = UrlRequest(f"{base_url}/models", headers={"Accept": "application/json"})
    with urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    models = data.get("data") or []
    if not models:
        raise ValueError("LM Studio is running but no model is loaded.")
    return str(models[0].get("id") or "")


def _call_llm(settings: dict, prompt: str, model: str | None = None) -> str:
    if note_quality.WRITING_RULES not in prompt:
        prompt = note_quality.WRITING_RULES + "\n" + prompt
    provider = settings.get("provider", "openai")
    if provider == "none":
        raise ValueError("AI synthesis is turned off in Settings.")
    model = model or _active_model(settings)
    api_key = settings.get("api_keys", {}).get(provider, "")
    max_tokens = int(settings.get("max_tokens", 1920))
    if provider not in {"openai", "anthropic", "openrouter", "lmstudio"}:
        raise ValueError(f"Unknown LLM provider: {provider}")
    if provider in {"openai", "anthropic", "openrouter"} and not api_key:
        raise ValueError(f"Missing {LLM_PROVIDER_LABELS.get(provider, provider)} API key.")
    # Reasoning-capable models spend part of the budget on hidden reasoning,
    # so give every provider the same output headroom GRIND needs for JSON.
    out_tokens = max(max_tokens, 6000)

    effort = str(settings.get("reasoning_effort") or "medium").strip().lower()

    if provider == "anthropic":
        # Map SKATE's reasoning effort onto Claude extended-thinking budgets.
        thinking_budgets = {"low": 2048, "medium": 8192, "high": 16384, "xhigh": 24576, "max": 32000}
        budget = thinking_budgets.get(effort, 0)
        if budget:
            out_tokens = max(out_tokens, budget + 4000)
        payload = {
            "model": model,
            "max_tokens": out_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if budget:
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        response = _post_json("https://api.anthropic.com/v1/messages", headers, payload)
        parts = [
            block.get("text", "")
            for block in response.get("content", [])
            if block.get("type") == "text"
        ]
        text = "\n".join(part for part in parts if part)
        if not text:
            raise ValueError("Anthropic returned no text content.")
        return text

    if provider == "openrouter":
        if not model:
            raise ValueError("Set an OpenRouter model id in Settings (for example anthropic/claude-sonnet-5).")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/SixSigmaEngineer/skate-workshop-os",
            "X-Title": "SKATE",
        }
        # OpenRouter accepts low/medium/high reasoning effort for capable models.
        or_effort = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}.get(effort, "")
        return _chat_completions("https://openrouter.ai/api/v1", headers, model, prompt, out_tokens, or_effort)

    if provider == "lmstudio":
        base_url = str(settings.get("lmstudio_base_url") or "http://127.0.0.1:1234/v1").rstrip("/")
        try:
            if not model:
                model = _lmstudio_default_model(base_url)
            return _chat_completions(base_url, {"Content-Type": "application/json"}, model, prompt, out_tokens)
        except (URLError, TimeoutError, ConnectionError, OSError) as e:
            raise ValueError(
                f"Could not reach LM Studio at {base_url}. Start LM Studio, load a model, "
                f"and enable the local server. ({e})"
            ) from e

    if provider == "openai":
        base_url = str(settings.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
        model_lower = model.strip().lower()
        is_gpt56 = bool(re.match(r"^gpt-5\.6(?:$|-)", model_lower))
        if not is_gpt56:
            raise ValueError("SKATE's LLM workflows require the GPT-5.6 model family.")
        is_reasoning = True
        # Reasoning models (GPT-5 / o-series) spend part of the token budget on
        # hidden reasoning, so give them extra headroom or the visible JSON gets
        # truncated mid-object and fails to parse.
        out_tokens = max(max_tokens, 6000) if is_reasoning else max_tokens
        payload = {
            "model": model,
            "input": prompt,
            "max_output_tokens": out_tokens,
            "text": {"format": {"type": "json_object"}},
        }
        # GPT-5.6 supports none/low/medium/high/xhigh/max. Keep the effort
        # explicit so interactive Spotter calls and quality-first GRIND calls
        # have intentional latency/quality tradeoffs.
        if is_gpt56:
            effort = str(settings.get("reasoning_effort") or "medium").strip().lower()
            if effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
                effort = "medium"
            payload["reasoning"] = {"effort": effort}
        # Reasoning models reject the temperature parameter.
        if not is_reasoning:
            payload["temperature"] = temperature
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = _post_json(f"{base_url}/responses", headers, payload)
        except ModelHTTPError as exc:
            if exc.status_code not in {400, 422} or "format" not in str(exc).lower():
                raise
            # Some models/endpoints may not accept the JSON-format hint; retry plain.
            payload.pop("text", None)
            response = _post_json(f"{base_url}/responses", headers, payload)
        if response.get("output_text"):
            return response["output_text"]
        parts = []
        for output in response.get("output", []):
            for content in output.get("content", []):
                if content.get("text"):
                    parts.append(content["text"])
        return "\n".join(parts)

    raise ValueError(f"Unknown LLM provider: {provider}")


def _scope_notice(entries) -> str:
    """Tell the user when a session is larger than one synthesis pass."""
    extra = len(entries) - MAX_SYNTHESIS_NOTES
    if extra <= 0:
        return ""
    return (
        f"This session has {len(entries)} active notes. AI synthesis reads the first "
        f"{MAX_SYNTHESIS_NOTES}, so {extra} were not included. Narrow the scope, or mark "
        "the key signals in the remaining notes so they carry into the next pass."
    )


def _grind_insights(entries, graph: dict) -> dict:
    settings = _load_settings()
    grind_settings = _grind_settings(settings)
    provider = grind_settings.get("provider", "openai")
    local = design_insights(entries, graph)
    local["mode"] = "local"
    local["scope_notice"] = _scope_notice(entries)
    local["provider"] = provider
    local["model"] = _active_model(grind_settings)
    local["reasoning_effort"] = grind_settings.get("reasoning_effort", "medium")
    local["error"] = ""

    if not _llm_available(grind_settings):
        if provider == "none":
            local["error"] = ""
            local["notice"] = "AI synthesis is off; showing SKATE's local synthesis."
        else:
            local["error"] = f"{_llm_unavailable_reason(grind_settings)}; showing local synthesis."
        return local

    try:
        text = _call_llm(grind_settings, _synthesis_prompt(entries, graph))
        ai = _normalize_ai_insights(_extract_json_object(text), entries)
        ai["mode"] = "ai"
        ai["provider"] = provider
        ai["model"] = _active_model(grind_settings)
        ai["reasoning_effort"] = grind_settings.get("reasoning_effort", "medium")
        ai["error"] = ""
        ai["marker_counts"] = local.get("marker_counts", {})
        ai["scope_notice"] = local.get("scope_notice", "")
        return ai
    except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
        local["error"] = f"AI synthesis failed; showing local synthesis. {e}"
        return local


def _grind_export_rows(insights: dict) -> list[list[str]]:
    rows = [[
        "Category",
        "Rank",
        "Title / Prompt",
        "Summary",
        "Source URL",
        "Capture Title",
        "Capture Summary",
        "Synthesis",
    ]]
    synthesis = f"{insights.get('mode', 'local')} / {insights.get('provider', '')} / {insights.get('model', '')}"
    for index, pain in enumerate(insights.get("pains", []), start=1):
        rows.append([
            "Pain Point",
            str(index),
            str(pain.get("title", "")),
            str(pain.get("summary", "")),
            str(pain.get("source_url", "")),
            str(pain.get("capture_title", "")),
            str(pain.get("capture_summary", "")),
            synthesis,
        ])
    for index, hmw in enumerate(insights.get("hmw_prompts", []), start=1):
        rows.append([
            "HMW Prompt",
            str(index),
            str(hmw.get("prompt", "")),
            str(hmw.get("source_title", "")),
            "",
            str(hmw.get("capture_title", "")),
            str(hmw.get("capture_summary", "")),
            synthesis,
        ])
    for index, solution in enumerate(insights.get("solutions", []), start=1):
        rows.append([
            "Solution Starter",
            str(index),
            str(solution.get("title", "")),
            str(solution.get("summary", "")),
            str(solution.get("source_url", "")),
            str(solution.get("capture_title", "")),
            str(solution.get("capture_summary", "")),
            synthesis,
        ])
    return rows


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_cell(value: str, row_index: int, col_index: int) -> str:
    ref = f"{_column_name(col_index)}{row_index}"
    value = xml_escape(str(value or ""))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{value}</t></is></c>'


def _make_xlsx(rows: list[list[str]]) -> bytes:
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(_xlsx_cell(value, row_index, col_index) for col_index, value in enumerate(row, start=1))
        sheet_rows.append(f'<row r="{row_index}">{cells}</row>')
    dimension = f"A1:{_column_name(max(len(row) for row in rows))}{len(rows)}"
    worksheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="{dimension}"/>
  <sheetViews><sheetView workbookViewId="0"/></sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="1" width="20" customWidth="1"/>
    <col min="2" max="2" width="8" customWidth="1"/>
    <col min="3" max="3" width="42" customWidth="1"/>
    <col min="4" max="4" width="80" customWidth="1"/>
    <col min="5" max="5" width="28" customWidth="1"/>
    <col min="6" max="6" width="42" customWidth="1"/>
    <col min="7" max="7" width="80" customWidth="1"/>
    <col min="8" max="8" width="28" customWidth="1"/>
  </cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
</worksheet>'''
    files = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''',
        "xl/workbook.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="GRIND Output" sheetId="1" r:id="rId1"/></sheets>
</workbook>''',
        "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>''',
        "xl/worksheets/sheet1.xml": worksheet,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _local_metadata_suggestion(title: str, body: str) -> dict:
    text = f"{title}\n{body}".lower()
    return {
        "tags": [],
        "themes": [
            theme
            for theme in CONSULTING_THEMES
            if any(word in text for word in theme.lower().split())
        ][:5],
        "entry_type": "pain" if any(word in text for word in ["pain", "friction", "problem"]) else "observation",
        "relationships": [],
        "reasoning": "Local consulting metadata suggestion. Add an OpenAI API key for GPT-5.6 theme extraction.",
        "mode": "local",
    }


def _classification_prompt(title: str, body: str) -> str:
    entry_types = ", ".join(ENTRY_TYPES.keys())
    themes = ", ".join(CONSULTING_THEMES)
    relationships = ", ".join(RELATIONSHIP_TYPES.keys())
    return f"""You are converting a SKATE workshop note into consultant memory metadata.

Classify by consulting intent.

Memory object types:
{entry_types}

Common themes, but generate better content-specific themes when useful:
{themes}

Relationship types:
{relationships}

Return clean signal text inside the JSON arrays only. Do not add bullets, Markdown headings, or prefixes such as #P: and #O:; SKATE adds its plain line-start markers after parsing the JSON.

Return only JSON with:
{{
  "entry_type": "one memory object type",
  "themes": ["3 to 7 semantic themes"],
  "relationships": [{{"type":"supports|contradicts|causes|leads_to|references|similar_to","target":"existing filename if obvious","note":"short evidence note"}}],
  "tags": ["3 to 7 short lowercase tags"],
  "reasoning": "one short sentence about the consulting meaning"
}}

Title: {title}

Markdown note:
{body[:6000]}
"""


def _compression_prompt(title: str, tags: str, body: str) -> str:
    return f"""Clean and compress this raw SKATE workshop note into organized consulting memory.

{note_quality.WRITING_RULES}
{note_quality.RELEVANCE_RULES}

The note may be dirty: shorthand, fragments, typos, half-finished bullets, and stream-of-consciousness capture. Rewrite it clean and concise while preserving meaning, names, commitments, and uncertainty. Do not invent anything that is not in the note.

Then organize the substance into SKATE's typed signals so each one appears in the knowledge graph. Every distinct action item belongs in "actions", every friction point in "pain_points", and so on — split combined thoughts into separate signals.

Return only JSON with:
{{
  "gist": "one sentence",
  "consulting_context": "the main consulting context for this note",
  "key_points": ["distinct context worth keeping as prose, without repeating signals"],
  "observations": ["distinct direct evidence or notable statements"],
  "pain_points": ["distinct friction points"],
  "actions": ["every distinct action item, each a single concrete follow-up"],
  "questions": ["distinct open questions"],
  "insights": ["interpretations or patterns grounded in the note"],
  "solutions": ["solutions or experiments proposed"],
  "recommendations": ["recommendations stated in the note"],
  "decisions": ["decisions actually made"],
  "agent_memory": "compact paragraph under 120 words written as reusable long-term memory",
  "excluded_topics": ["short labels for unrelated topics omitted"]
}}

Title: {title}
Tags: {tags}

Markdown note:
{body}
"""


def _local_note_compression(title: str, tags: str, body: str) -> dict:
    extracted = note_quality.local_signals(body, f"{title} {tags}")
    evidence = [item for key in note_quality.SIGNAL_KEYS.values() for item in extracted[key]]
    context = extracted["context"]
    return {
        "gist": _plain_text_excerpt(" ".join(evidence[:3]), 500)
                or "No structured workshop signals were identified. Review the retained context below.",
        "consulting_context": " ".join((tags or title).split()),
        "key_points": context,
        **{key: extracted[key] for key in note_quality.SIGNAL_KEYS.values()},
        "agent_memory": "",
        "mode": "local",
    }


def _plain_text_excerpt(text: str, limit: int) -> str:
    text = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    text = re.sub(r"(?m)^>\s?", "", text)
    text = re.sub(r"(?m)^#+\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "..."


def _normalize_compression(raw: dict, fallback: dict) -> dict:
    def list_of_strings(key: str) -> list[str]:
        values = raw.get(key, fallback.get(key, []))
        if not isinstance(values, list):
            return fallback.get(key, [])
        out = []
        for item in values:
            if not isinstance(item, str):
                continue
            text = item.strip()
            text = re.sub(r"^[-*•]\s*", "", text).strip()
            if key in note_quality.SIGNAL_KEYS.values():
                text = re.sub(
                    r"^(?:\\?#\s*[OPAQISRD](?:\s*:|\s+)|(?:Observation|Pain|Action(?:\s+Item)?|(?:Open\s+)?Question|Insight|Solution|Recommendation|Decision):\s*)",
                    "",
                    text,
                    flags=re.I,
                ).strip()
            if text and text not in out:
                out.append(text)
        return out

    return {
        "gist": str(raw.get("gist", "")).strip() or fallback["gist"],
        "consulting_context": str(raw.get("consulting_context", "")).strip() or fallback["consulting_context"],
        "key_points": list_of_strings("key_points"),
        **{key: list_of_strings(key) for key in note_quality.SIGNAL_KEYS.values()},
        "agent_memory": str(raw.get("agent_memory", "")).strip() or fallback["agent_memory"],
        "mode": "ai",
    }


def _compression_markdown(compression: dict) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    def signals(code: str, items: list[str]) -> str:
        return "\n".join(f"#{code}: {item}" for item in items)

    sections = [
        "## Cleaned Notes",
        f"**Gist:** {compression['gist']}",
        f"**Context:** {compression['consulting_context']}",
    ]
    if compression.get("key_points") and compression.get("mode") != "local":
        sections.append("**Key points**\n\n" + bullets(compression["key_points"]))
    signal_lines = "\n".join(
        part
        for part in (
            signals("O", compression.get("observations", [])),
            signals("P", compression.get("pain_points", [])),
            signals("Q", compression.get("questions", [])),
            signals("I", compression.get("insights", [])),
            signals("A", compression.get("actions", [])),
            signals("S", compression.get("solutions", [])),
            signals("R", compression.get("recommendations", [])),
        )
        if part
    )
    if signal_lines:
        sections.append("**Signals**\n\n" + signal_lines)
    if compression.get("decisions"):
        sections.append("**Decisions**\n\n" + bullets(compression["decisions"]))
    if compression.get("key_points") and compression.get("mode") == "local":
        sections.append("**Additional context to review (not classified)**\n\n" + bullets(compression["key_points"]))
    if compression.get("agent_memory"):
        sections.append("**Agent memory**\n" + compression["agent_memory"])
    return "\n\n".join(sections) + "\n"


def _transcript_summary_prompt(title: str, transcript: str) -> str:
    return f"""Turn this raw workshop or meeting transcript into clean, concise SKATE meeting notes.

{note_quality.WRITING_RULES}
{note_quality.RELEVANCE_RULES}

Use only evidence present in the transcript. Remove filler, repetition, false starts, and transcription noise. Keep names, commitments, uncertainty, and important context accurate. Distinguish observed evidence from interpretation.

Return only JSON with:
{{
  "summary": "short paragraph",
  "observations": ["direct evidence, facts, or notable statements"],
  "pain_points": ["pain points or friction"],
  "actions": ["action items"],
  "questions": ["open questions"],
  "solutions": ["solutions or experiments proposed"],
  "recommendations": ["recommendations made"],
  "insights": ["interpretations or patterns grounded in the transcript"],
  "decisions": ["decisions actually made"],
  "key_points": ["important context not already captured as a signal"],
  "tags": ["3 to 7 lowercase tags"],
  "excluded_topics": ["short labels for unrelated topics omitted"]
}}

Title: {title}

Transcript:
{transcript}
"""


def _local_transcript_summary(title: str, transcript: str) -> dict:
    extracted = note_quality.local_signals(transcript, title)
    relevant = [item for key in note_quality.SIGNAL_KEYS.values() for item in extracted[key]]
    return {
        "summary": _plain_text_excerpt(" ".join(relevant[:4]), 650)
                   or "No structured workshop signals were identified. Review the retained context below.",
        **{key: extracted[key] for key in note_quality.SIGNAL_KEYS.values()},
        "key_points": extracted["context"],
        "tags": [], "mode": "local",
    }


def _normalize_transcript_summary(raw: dict, fallback: dict) -> dict:
    def strings(key: str) -> list[str]:
        values = raw.get(key, fallback.get(key, []))
        if not isinstance(values, list):
            return fallback.get(key, [])
        out = []
        for item in values:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text and text not in out:
                out.append(text)
        return out

    tags = []
    for tag in raw.get("tags", []):
        tag = re.sub(r"[^a-z0-9-]+", "-", str(tag).strip().lower()).strip("-")
        if tag and tag not in tags:
            tags.append(tag)

    return {
        "summary": str(raw.get("summary", "")).strip() or fallback["summary"],
        **{key: strings(key) for key in note_quality.SIGNAL_KEYS.values()},
        "key_points": strings("key_points"),
        "tags": tags[:7],
        "mode": "ai",
    }


def _transcript_summary_markdown(summary: dict) -> str:
    signals = []
    for code, key in (
        ("O", "observations"),
        ("P", "pain_points"),
        ("A", "actions"),
        ("Q", "questions"),
        ("S", "solutions"),
        ("R", "recommendations"),
        ("I", "insights"),
    ):
        signals.extend(f"- #{code}: {item}" for item in summary.get(key, []) if str(item).strip())
    signals.extend(f"- Decision: {item}" for item in summary.get("decisions", []))
    if summary.get("mode") != "local":
        signals.extend(f"- {item}" for item in summary.get("key_points", []))
    signal_text = "\n".join(signals) if signals else "- No structured signals were captured."
    if summary.get("mode") == "local" and summary.get("key_points"):
        signal_text += "\n\n### Additional context to review (not classified)\n\n"
        signal_text += "\n".join(f"- {item}" for item in summary["key_points"])

    return f"""## Meeting Notes

{summary["summary"]}

### Key Signals
{signal_text}
"""


def _spotter_mode(mode_id: str) -> dict:
    return next((mode for mode in SPOTTER_MODES if mode["id"] == mode_id), SPOTTER_MODES[0])


def _options_with_current(options: list[str], current: str) -> list[str]:
    current = (current or "").strip()
    if current and current not in options:
        return [current] + options
    return options


_RETRIEVAL_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "it", "its", "i", "you", "we", "they", "my", "our", "your", "me",
    "us", "help", "can", "could", "would", "should", "do", "does", "did", "how",
    "what", "why", "when", "who", "where", "which", "please", "need", "want",
    "about", "through", "here", "there", "at", "as", "by", "so", "if", "then",
    "from", "into", "out", "up", "down", "have", "has", "had", "will", "just",
    "like", "get", "got", "let", "lets", "talk", "tell", "show", "give", "go",
}


def _retrieval_terms(text: str) -> list[str]:
    """Lowercase content words from a query, stopwords and short tokens removed."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    seen, out = set(), []
    for w in words:
        if len(w) > 2 and w not in _RETRIEVAL_STOPWORDS and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _spotter_session_context(session: str, query: str = "", top_k: int = 5) -> str:
    """Hybrid RAG: return only the session notes most relevant to the query.

    Ranking blends semantic embedding similarity (when a local backend such as
    Ollama or fastembed is available — see ui/embeddings.py) with keyword
    overlap (title/tags/themes weighted higher than body). If nothing matches,
    fall back to the most recent notes so there is still grounding context.
    This keeps the prompt small and on-topic instead of dumping every note.
    """
    if not session:
        return "No active session was supplied. Work from the live capture only."
    entries = filter_entries(load_all_entries(), session=session)
    if not entries:
        return "An active session was supplied, but no existing notes were found for it yet."

    terms = _retrieval_terms(query)

    def score(entry) -> int:
        if not terms:
            return 0
        strong = " ".join([entry.title] + list(entry.tags) + list(entry.themes)).lower()
        weak = (entry.summary or entry.body or "").lower()
        total = 0
        for term in terms:
            if term in strong:
                total += 3
            if term in weak:
                total += 1
        return total

    top, mode = embeddings.rank_entries(entries, query, score, top_k=top_k)
    headers = {
        "hybrid": "Most relevant notes from this session (semantic + keyword retrieval):",
        "lexical": "Most relevant notes from this session (retrieved for this question):",
        "recent": "Recent notes from this session (no direct keyword match):",
    }
    header = headers[mode]

    lines = [header]
    for entry in top:
        tags = ", ".join(entry.tags[:6])
        summary = _plain_text_excerpt(entry.summary or entry.body, 320)
        lines.append(f"- {entry.title} [{entry.type_label}] {tags}: {summary}")
    return "\n".join(lines)


def _workshop_knowledge_context() -> str:
    if not WORKSHOP_KNOWLEDGE_DIR.exists():
        return "No workshop knowledge document folder was found."
    docs = sorted(
        path for path in WORKSHOP_KNOWLEDGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".md", ".txt"}
    )
    if not docs:
        return "The workshop knowledge folder exists but has no supported documents yet."
    focus = [
        "Process analysis and Gemba: observe current work, separate stated process from actual work, identify handoffs, queues, rework, hidden work, decision points, system friction, and pain points.",
        "Lean improvement: use DMAIC, DOWNTIME wastes, VA/NVA/NVAR, 5 Whys, root-cause hypotheses, current/future-state mapping, countermeasures, control plans, and measurable operational outcomes.",
        "Kaizen / RIE: help with charters, case for change, specific problem statements, event prep, 2-5 day event flow, rapid experiments, follow-up, ownership, and sustainment.",
        "Design thinking / HCD: use empathy, VOC, How Might We framing, ideation, prototyping, testing, desirability/feasibility/viability, and facilitation moves.",
        "AI and automation opportunity spotting: identify where AI, workflow automation, knowledge graphs, dashboards, integrations, or better decision support could reduce waste and create ROI.",
    ]
    files = "\n".join(f"- {path.stem} ({path.suffix.lower().lstrip('.')})" for path in docs[:30])
    return "Workshop knowledge corpus focus:\n" + "\n".join(f"- {item}" for item in focus) + "\n\nAvailable documents:\n" + files


def _spotter_prompt(mode: dict, text: str, session: str, session_context: str, settings: dict) -> str:
    themes = ", ".join(CONSULTING_THEMES)
    persona = str(settings.get("spotter_persona", DEFAULT_SETTINGS["spotter_persona"])).strip()
    methodology = str(settings.get("spotter_methodology", DEFAULT_SETTINGS["spotter_methodology"])).strip()
    style = str(settings.get("spotter_style", DEFAULT_SETTINGS["spotter_style"])).strip()
    return f"""{persona}

METHODOLOGY STACK:
{methodology}

STYLE:
{style}

Mode: {mode['label']}
Instruction: {mode['prompt']}
Session: {session or 'unspecified'}
Common themes: {themes}

{note_quality.WRITING_RULES}
{note_quality.RELEVANCE_RULES}

Relevant session notes:
{session_context[:3500]}

Workshop knowledge documents:
{_workshop_knowledge_context()[:2500]}

Return only JSON with:
{{
  "spoken_response": "brief facilitator response to say out loud",
  "title": "short SKATE note title",
  "entry_type": "{mode['entry_type']}",
  "themes": ["3 to 7 semantic themes"],
  "summary": "short paragraph",
  "evidence": ["observations or quotes"],
  "insights": ["patterns, implications, or root-cause hypotheses"],
  "recommendations": ["practical next moves"],
  "actions": ["specific action items"],
  "questions": ["follow-up workshop questions"],
  "relationships": [{{"type":"supports|contradicts|causes|leads_to|references|similar_to","target":"","note":"relationship note if known"}}]
}}

Workshop capture:
{_select_body_excerpt(text, 12000)[0]}
"""


def _local_spotter_response(mode: dict, text: str, focus: str = "") -> dict:
    extracted = note_quality.local_signals(text, focus)
    cleaned = extracted["review"]["text"]
    summary = _plain_text_excerpt(cleaned, 500)
    return {
        "spoken_response": "Workshop capture ready for review." if cleaned else "No workshop content was identified in this capture.",
        "title": f"{mode['label']}: {_plain_text_excerpt(cleaned, 70) or 'No workshop content'}",
        "entry_type": mode["entry_type"] if cleaned else "note",
        "themes": [], "summary": summary,
        "evidence": extracted["observations"],
        "insights": extracted["insights"], "recommendations": extracted["recommendations"],
        "actions": extracted["actions"], "questions": extracted["questions"],
        "relationships": [], "mode": "local",
    }


def _normalize_spotter_response(raw: dict, fallback: dict, mode: dict) -> dict:
    def strings(key: str, limit: int) -> list[str]:
        values = raw.get(key, [])
        if not isinstance(values, list):
            return fallback.get(key, [])
        return [str(value).strip() for value in values if str(value).strip()][:limit]

    return {
        "spoken_response": str(raw.get("spoken_response", "")).strip() or fallback["spoken_response"],
        "title": str(raw.get("title", "")).strip() or fallback["title"],
        "entry_type": _clean_entry_type(str(raw.get("entry_type", mode["entry_type"]))),
        "themes": _coerce_theme_csv(", ".join(strings("themes", 7))),
        "summary": str(raw.get("summary", "")).strip() or fallback["summary"],
        "evidence": strings("evidence", 8),
        "insights": strings("insights", 8),
        "recommendations": strings("recommendations", 8),
        "actions": strings("actions", 8),
        "questions": strings("questions", 8),
        "relationships": raw.get("relationships", []) if isinstance(raw.get("relationships", []), list) else [],
        "mode": "ai",
    }


def _spotter_markdown(result: dict) -> str:
    def section(title: str, items: list[str]) -> str:
        body = "\n".join(f"- {item}" for item in items) if items else "- None captured"
        return f"## {title}\n\n{body}"

    return "\n\n".join(
        [
            f"# {result['title']}",
            "## Summary\n\n" + result["summary"],
            section("Evidence", result["evidence"]),
            section("Insights", result["insights"]),
            section("Recommendations", result["recommendations"]),
            section("Action Items", result["actions"]),
            section("Open Questions", result["questions"]),
        ]
    )


def _decode_wav_for_whisper(audio_bytes: bytes) -> tuple["np.ndarray", int]:
    import io
    import wave

    import numpy as np

    with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width == 1:
        audio = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        audio = (audio - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        signed = (
            raw[:, 0].astype(np.int32)
            | (raw[:, 1].astype(np.int32) << 8)
            | (raw[:, 2].astype(np.int32) << 16)
        )
        signed = np.where(signed & 0x800000, signed - 0x1000000, signed)
        audio = signed.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError("This WAV format is not supported yet.")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    target_rate = 16000
    if frame_rate != target_rate and len(audio) > 1:
        old_index = np.linspace(0, len(audio) - 1, num=len(audio), dtype=np.float32)
        new_len = max(1, int(len(audio) * target_rate / frame_rate))
        new_index = np.linspace(0, len(audio) - 1, num=new_len, dtype=np.float32)
        audio = np.interp(new_index, old_index, audio).astype(np.float32)
        frame_rate = target_rate

    return audio.astype(np.float32), frame_rate


def _find_local_ffmpeg() -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return Path(ffmpeg)
    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
        alias = SKATE_ROOT / "tools" / "ffmpeg.exe"
        if bundled.exists():
            alias.parent.mkdir(parents=True, exist_ok=True)
            if not alias.exists():
                shutil.copy2(bundled, alias)
            return alias
    except Exception:
        pass
    candidates = [
        SKATE_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        SKATE_ROOT / "tools" / "ffmpeg.exe",
        SKATE_ROOT / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(sys.executable).resolve().parent / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _whisper_model_root() -> Path:
    model_root = SKATE_ROOT / "models" / "whisper"
    model_root.mkdir(parents=True, exist_ok=True)
    return model_root


def _faster_whisper_transcribe(audio_bytes: bytes | Path, filename: str, content_type: str, model_name: str, progress_callback=None) -> str:
    """Local transcription via faster-whisper (CTranslate2).

    This engine ships inside the packaged app: no PyTorch, no external
    ffmpeg (PyAV decodes), and models download on first use into
    models/whisper.
    """
    from faster_whisper import WhisperModel

    def report(percent: int, phase: str) -> None:
        if progress_callback:
            progress_callback(max(0, min(99, int(percent))), phase)

    suffix = (Path(filename).suffix or mimetypes.guess_extension(content_type) or ".webm").lower()
    report(4, "Loading Whisper model")
    cache_key = f"faster-whisper:{model_name}"
    with WHISPER_MODEL_LOCK:
        if WHISPER_MODEL_CACHE.get("name") == cache_key and WHISPER_MODEL_CACHE.get("model") is not None:
            model = WHISPER_MODEL_CACHE["model"]
            report(6, "Whisper model ready")
        else:
            try:
                model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(_whisper_model_root()),
                )
            except Exception as exc:
                message = str(exc)
                if any(marker in message.lower() for marker in ("connection", "download", "resolve", "offline", "urlopen")):
                    raise RuntimeError(
                        f"The local Whisper '{model_name}' model is not downloaded yet. Connect to the internet once; SKATE stores it in models\\whisper for offline use after that."
                    ) from exc
                raise
            WHISPER_MODEL_CACHE["name"] = cache_key
            WHISPER_MODEL_CACHE["model"] = model

    import tempfile
    import contextlib

    with tempfile.TemporaryDirectory(prefix="skate-whisper-") as directory:
        work = Path(directory)
        if isinstance(audio_bytes, Path):
            source = audio_bytes
        else:
            source = work / ("recording" + suffix)
            source.write_bytes(audio_bytes)
        report(8, "Decoding recording in ten-minute sections")
        parts: list[str] = []
        with contextlib.closing(audio_sections(source, work)) as sections:
            for section, offset, duration in sections:
                segments, info = model.transcribe(str(section), beam_size=5)
                for segment in segments:
                    parts.append(segment.text)
                    if duration > 0:
                        report(12 + round(83 * min(1.0, (offset + float(segment.end)) / duration)), "Transcribing recording")
        report(98, "Finalizing transcript")
        return " ".join(part.strip() for part in parts if part.strip()).strip()


def _local_whisper_transcribe(audio_bytes: bytes | Path, filename: str, content_type: str, model_name: str, progress_callback=None) -> str:
    def report(percent: int, phase: str) -> None:
        if progress_callback:
            progress_callback(max(0, min(99, int(percent))), phase)

    # Prefer the bundled faster-whisper engine (present in packaged builds
    # and fresh source setups); fall back to classic openai-whisper for
    # environments that installed it via Install Local Whisper.bat.
    try:
        import faster_whisper  # noqa: F401
        return _faster_whisper_transcribe(audio_bytes, filename, content_type, model_name, progress_callback)
    except ImportError:
        pass

    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Local Whisper is not installed yet. Close SKATE and reopen Start SKATE.pyw or SKATE.exe so SKATE can install the new local transcription package. "
            "If it still fails, run Install Local Whisper.ps1 in the SKATE folder."
        ) from exc

    suffix = (Path(filename).suffix or mimetypes.guess_extension(content_type) or ".webm").lower()
    ffmpeg_path = _find_local_ffmpeg()
    if ffmpeg_path:
        os.environ["PATH"] = f"{ffmpeg_path.parent}{os.pathsep}{os.environ.get('PATH', '')}"

    report(4, "Loading Whisper model")
    try:
        with WHISPER_MODEL_LOCK:
            if WHISPER_MODEL_CACHE.get("name") == model_name and WHISPER_MODEL_CACHE.get("model") is not None:
                model = WHISPER_MODEL_CACHE["model"]
                report(6, "Whisper model ready")
            else:
                model = whisper.load_model(model_name, download_root=str(_whisper_model_root()))
                WHISPER_MODEL_CACHE["name"] = model_name
                WHISPER_MODEL_CACHE["model"] = model
    except Exception as exc:
        message = str(exc)
        if "urlopen" in message or "socket" in message or "download" in message.lower():
            raise RuntimeError(
                f"The local Whisper '{model_name}' model is not downloaded yet. Run Install Local Whisper.ps1 once while online; SKATE will store the model in models\\whisper for local use after that."
            ) from exc
        raise
    def run_whisper(source) -> dict:
        import importlib

        transcribe_module = importlib.import_module("whisper.transcribe")
        original_tqdm = transcribe_module.tqdm.tqdm

        class SkateProgressTqdm(original_tqdm):
            def update(self, amount=1):
                result = super().update(amount)
                if self.total:
                    report(12 + round(83 * min(1.0, self.n / self.total)), "Transcribing recording")
                return result

        # Whisper exposes frame progress through tqdm. Protect the temporary
        # hook so simultaneous local jobs cannot overwrite one another.
        with WHISPER_PROGRESS_LOCK:
            transcribe_module.tqdm.tqdm = SkateProgressTqdm
            try:
                report(12, "Transcribing recording")
                return model.transcribe(source, fp16=False, verbose=False)
            finally:
                transcribe_module.tqdm.tqdm = original_tqdm

    if isinstance(audio_bytes, Path):
        if audio_bytes.stat().st_size > 250 * 1024 * 1024:
            raise RuntimeError("Large recordings require faster-whisper. Run Start SKATE.bat to install the current requirements.")
        result = run_whisper(str(audio_bytes))
        return str(result.get("text", "")).strip()

    if suffix == ".wav" or content_type in {"audio/wav", "audio/x-wav", "audio/wave"}:
        try:
            report(8, "Decoding recording")
            audio, _frame_rate = _decode_wav_for_whisper(audio_bytes)
            result = run_whisper(audio)
            report(98, "Finalizing transcript")
            return str(result.get("text", "")).strip()
        except Exception as exc:
            if not ffmpeg_path:
                raise RuntimeError(
                    "This WAV file could not be decoded directly. Run Install Local Whisper.ps1 again to add SKATE's audio decoder helper, then reopen SKATE."
                ) from exc

    if not ffmpeg_path:
        raise RuntimeError(
            "This audio type needs SKATE's local audio decoder helper. WAV files can run now; for mp3, m4a, webm, or mp4, run Install Local Whisper.ps1 again."
        )

    temp_path = None
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(audio_bytes)
            temp_path = Path(fh.name)
        report(8, "Decoding recording")
        result = run_whisper(str(temp_path))
        report(98, "Finalizing transcript")
        return str(result.get("text", "")).strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Local Whisper needs its audio decoder helper. Run Install Local Whisper.ps1 again, then reopen SKATE."
        ) from exc
    finally:
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _normalize_metadata_suggestion(raw: dict, fallback: dict) -> dict:
    tags = []
    for tag in raw.get("tags", []):
        tag = re.sub(r"[^a-z0-9-]+", "-", str(tag).strip().lower()).strip("-")
        if tag and tag not in tags:
            tags.append(tag)
    return {
        "tags": tags[:7],
        "themes": _coerce_theme_csv(", ".join(str(t) for t in raw.get("themes", [])))[:7],
        "entry_type": _clean_entry_type(str(raw.get("entry_type", fallback.get("entry_type", "note")))),
        "relationships": raw.get("relationships", []) if isinstance(raw.get("relationships", []), list) else [],
        "reasoning": str(raw.get("reasoning", "")).strip() or fallback["reasoning"],
        "mode": "ai",
    }


CONNECTION_REVIEW_RELATIONSHIPS = {"supports", "contradicts", "causes", "leads_to", "references"}


def _active_session_entries(session_key: str) -> list:
    """Return active memory objects in one session for bounded review."""
    session = _slugify(session_key)
    session_path = SESSIONS / session / "README.md"
    if session_path.exists():
        session_post = frontmatter.load(session_path, encoding="utf-8")
        if str(session_post.metadata.get("status", "active")).strip().lower() == "inactive":
            return []
    return [
        entry
        for entry in filter_entries(load_all_entries(), session=session)
        if entry.status.strip().lower() != "inactive"
        and entry.session_status.strip().lower() != "inactive"
    ]


def _local_connection_review(entries: list) -> dict:
    """Audit obvious missing metadata without inventing semantic evidence links."""
    metadata = []
    for entry in entries:
        fallback = _local_metadata_suggestion(entry.title, entry.body)
        themes = list(entry.themes)
        for theme in fallback["themes"]:
            if theme not in themes:
                themes.append(theme)
        if themes != entry.themes:
            metadata.append(
                {
                    "file_id": entry.file_id,
                    "title": entry.title,
                    "current_type": entry.entry_type,
                    "entry_type": entry.entry_type,
                    "current_themes": list(entry.themes),
                    "themes": themes[:7],
                    "current_tags": list(entry.tags),
                    "tags": list(entry.tags),
                    "reason": "Local review found a consulting theme in the note text.",
                }
            )
    return {"metadata": metadata, "relationships": [], "mode": "local"}


def _connection_review_prompt(session_label: str, entries: list) -> str:
    per_note_limit = max(350, min(2200, 36000 // max(1, len(entries))))
    notes = []
    for entry in entries:
        signals = {
            marker_type: texts[:8]
            for marker_type, texts in capture_markers(entry).items()
            if texts
        }
        notes.append(
            {
                "file_id": entry.file_id,
                "title": entry.title,
                "type": entry.entry_type,
                "themes": entry.themes,
                "tags": entry.tags,
                "existing_relationships": entry.relationships,
                "signals": signals,
                "body": entry.body[:per_note_limit],
            }
        )
    return f"""You are reviewing one SKATE workshop session for missing metadata and evidence connections.

Session: {session_label}

Use only the supplied active notes. Never invent a note or identifier. Prefer a small set of strong,
defensible relationships over many weak similarities. Shared themes are already connected automatically,
so do not create relationships merely because two notes share a theme.

Return only JSON with:
{{
  "metadata": [
    {{
      "file_id": "exact supplied file_id",
      "entry_type": "one valid memory object type",
      "themes": ["3 to 7 consistent semantic themes"],
      "tags": ["3 to 7 short lowercase tags"],
      "reason": "why this metadata needs attention"
    }}
  ],
  "relationships": [
    {{
      "source": "exact supplied file_id",
      "target": "different exact supplied file_id",
      "type": "supports|contradicts|causes|leads_to|references",
      "note": "short evidence-grounded explanation"
    }}
  ]
}}

Metadata rules:
- Include a metadata item only when metadata is missing, generic, inconsistent, or clearly incomplete.
- Preserve good existing themes and tags; include them in the proposed arrays alongside additions.
- Do not change a specific object type without clear evidence.
- Use consistent spelling and capitalization for themes across the session.

Relationship rules:
- Do not repeat an existing relationship in either direction.
- A hashtag signal is evidence inside its parent note; connect the parent notes when their content has a
  meaningful supports, contradicts, causes, leads_to, or references relationship.
- Each relationship explanation must make the connection reviewable by a human.
- Return at most 20 metadata items and 24 relationships.

Valid memory object types: {", ".join(ENTRY_TYPES.keys())}

Session notes:
{json.dumps(notes, ensure_ascii=False)}
"""


def _normalize_connection_review(raw: dict, entries: list, mode: str = "ai") -> dict:
    by_id = {entry.file_id: entry for entry in entries}
    metadata = []
    seen_metadata = set()
    for item in raw.get("metadata", []) if isinstance(raw.get("metadata", []), list) else []:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("file_id", "")).strip()
        entry = by_id.get(file_id)
        if entry is None or file_id in seen_metadata:
            continue
        themes = list(entry.themes)
        proposed_themes = item.get("themes", []) if isinstance(item.get("themes", []), list) else []
        for theme in _coerce_theme_csv(", ".join(str(value) for value in proposed_themes)):
            if theme not in themes:
                themes.append(theme)
        tags = list(entry.tags)
        proposed_tags = item.get("tags", []) if isinstance(item.get("tags", []), list) else []
        for value in proposed_tags:
            tag = re.sub(r"[^a-z0-9-]+", "-", str(value).strip().lower()).strip("-")
            if tag and tag not in tags:
                tags.append(tag)
        entry_type = _clean_entry_type(str(item.get("entry_type", entry.entry_type)))
        if themes == entry.themes and tags == entry.tags and entry_type == entry.entry_type:
            continue
        seen_metadata.add(file_id)
        metadata.append(
            {
                "file_id": file_id,
                "title": entry.title,
                "current_type": entry.entry_type,
                "entry_type": entry_type,
                "current_themes": list(entry.themes),
                "themes": themes[:7],
                "current_tags": list(entry.tags),
                "tags": tags[:7],
                "reason": str(item.get("reason", "")).strip() or "Metadata gap found during session review.",
            }
        )

    existing = set()
    for entry in entries:
        for relationship in entry.relationships:
            target = str(relationship.get("target", "")).strip()
            target_entry = by_id.get(target) or next(
                (candidate for candidate in entries if candidate.path.name == target), None
            )
            if target_entry:
                existing.add((entry.file_id, target_entry.file_id, relationship.get("type", "references")))
                existing.add((target_entry.file_id, entry.file_id, relationship.get("type", "references")))

    relationships = []
    seen_relationships = set()
    for item in raw.get("relationships", []) if isinstance(raw.get("relationships", []), list) else []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        rel_type = str(item.get("type", "")).strip().lower().replace("-", "_")
        key = (source, target, rel_type)
        reverse_key = (target, source, rel_type)
        if (
            source not in by_id
            or target not in by_id
            or source == target
            or rel_type not in CONNECTION_REVIEW_RELATIONSHIPS
            or key in existing
            or reverse_key in existing
            or key in seen_relationships
            or reverse_key in seen_relationships
        ):
            continue
        note = str(item.get("note", "")).strip()
        if not note:
            continue
        seen_relationships.add(key)
        relationships.append(
            {
                "source": source,
                "source_title": by_id[source].title,
                "target": target,
                "target_title": by_id[target].title,
                "type": rel_type,
                "type_label": RELATIONSHIP_TYPES[rel_type],
                "note": note[:300],
            }
        )
    return {"metadata": metadata[:20], "relationships": relationships[:24], "mode": mode}


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "untitled"


def _coerce_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _coerce_theme_csv(value: str) -> list[str]:
    themes = []
    for part in _coerce_csv(value):
        clean = re.sub(r"\s+", " ", part).strip()
        if clean and clean not in themes:
            themes.append(clean)
    return themes


def _parse_relationship_lines(value: str) -> list[dict[str, str]]:
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


def _relationship_lines(relationships: list[dict[str, str]]) -> str:
    lines = []
    for rel in relationships:
        line = f"{rel.get('type', 'references')} | {rel.get('target', '')}"
        if rel.get("note"):
            line += f" | {rel['note']}"
        lines.append(line)
    return "\n".join(lines)


def _clean_entry_type(value: str) -> str:
    cleaned = (value or "note").strip().lower()
    return cleaned if cleaned in ENTRY_TYPES else "note"


def _notes_folder() -> Path:
    """Folder where new notes are written inside the vault."""
    folder = CONVERSATIONS / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _normalize_newlines(text: str) -> str:
    """Collapse CRLF/CR to LF.

    HTML form submission normalises every textarea value to CRLF, so a note
    round-tripped through the editor arrives here full of \r\n. Left alone it
    reaches write_text() below, which on Windows translates each \n to \r\n
    again and produces \r\r\n - read back as two line breaks. Every save then
    doubles the blank lines in the note.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_note(path: Path, post) -> None:
    """Write a note with LF endings regardless of platform.

    newline="" stops Python translating \n to os.linesep on Windows. The vault
    is git-tracked and shared between machines, so one ending everywhere.
    """
    post.content = _normalize_newlines(post.content or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post), encoding="utf-8", newline="")


def _write_entry(
    path: Path,
    title: str,
    entry_date: str,
    entry_type: str,
    session: str,
    session_label: str,
    session_status: str,
    tags: list[str],
    themes: list[str],
    relationships: list[dict[str, str]],
    status: str,
    source: str,
    body: str,
    lineup_status: str = "",
    lineup_kind: str = "action",
    owner: str = "",
    due_date: str = "",
    cadence: str = "once",
    last_completed: str = "",
    captured_from: str = "",
):
    metadata = {
        "title": title,
        "date": entry_date,
        "type": _clean_entry_type(entry_type),
        "session": _slugify(session) if session else "",
        "session_label": session_label.strip(),
        "session_status": session_status.strip() or "active",
        "tags": tags,
        "themes": themes,
        "participants": ["Facilitator"],
        "status": status,
        "related": [],
        "relationships": relationships,
        "source": source,
    }
    if _clean_entry_type(entry_type) == "action":
        metadata.update(
            {
                "lineup_status": lineup_status if lineup_status in {"open", "landed"} else "open",
                "lineup_kind": lineup_kind if lineup_kind in {"action", "standard_work"} else "action",
                "owner": owner.strip(),
                "due_date": due_date.strip(),
                "cadence": cadence if cadence in LINEUP_CADENCES else "once",
                "last_completed": last_completed.strip(),
                "captured_from": captured_from.strip(),
            }
        )
    post = frontmatter.Post(_normalize_newlines(body).strip() + "\n", **metadata)
    _write_note(path, post)


def _default_note_body(title: str, summary: str = "") -> str:
    first_observation = summary.strip()
    observation_line = f"#O: {first_observation}" if first_observation else "#O: "
    return f"""# {title}

## Meeting notes

{observation_line}
#P:
#Q:
#A:

"""


async def _read_form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _checked(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def _embedded_actions(entry) -> list[dict[str, str]]:
    """Return actionable #A bullets captured inside an ordinary memory object."""
    actions = []
    for captured in dict.fromkeys(capture_markers(entry).get("action", [])):
        text = captured.strip()
        if not text:
            continue
        fingerprint = hashlib.sha1(f"{entry.file_id}\n{text}".encode("utf-8")).hexdigest()[:12]
        actions.append(
            {
                "text": text,
                "source_id": entry.file_id,
                "source_title": entry.title,
                "session": entry.session,
                "session_label": entry.session_display if entry.session else "",
                "fingerprint": fingerprint,
                "captured_from": f"{entry.file_id}#{fingerprint}",
            }
        )
    return actions


def _next_due_date(current: str, cadence: str) -> str:
    try:
        anchor = date.fromisoformat(current) if current else date.today()
    except ValueError:
        anchor = date.today()
    anchor = max(anchor, date.today())
    if cadence == "daily":
        return (anchor + timedelta(days=1)).isoformat()
    if cadence == "weekdays":
        candidate = anchor + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    if cadence == "weekly":
        return (anchor + timedelta(days=7)).isoformat()
    if cadence == "monthly":
        year = anchor.year + (1 if anchor.month == 12 else 0)
        month = 1 if anchor.month == 12 else anchor.month + 1
        return date(year, month, min(anchor.day, monthrange(year, month)[1])).isoformat()
    return ""


def _lineup_context(entries, session: str = "") -> dict:
    today = date.today().isoformat()
    tracked = [entry for entry in entries if entry.entry_type == "action" and entry.status != "inactive"]
    if session:
        tracked = [entry for entry in tracked if entry.session == session]
    tracked.sort(key=lambda entry: (entry.lineup_status == "landed", entry.due_date or "9999-12-31", entry.title.lower()))
    standard_work = [entry for entry in tracked if entry.lineup_kind == "standard_work"]
    actions = [entry for entry in tracked if entry.lineup_kind != "standard_work"]
    promoted = {entry.captured_from for entry in load_all_entries() if entry.captured_from}
    captured = []
    for entry in entries:
        if entry.entry_type == "action" or entry.status == "inactive":
            continue
        if session and entry.session != session:
            continue
        for action in _embedded_actions(entry):
            action["promoted"] = action["captured_from"] in promoted
            captured.append(action)
    return {
        "lineup_actions": actions,
        "standard_work": standard_work,
        "captured_actions": captured,
        "lineup_today": today,
        "lineup_open_count": sum(entry.lineup_status != "landed" for entry in actions),
        "lineup_landed_count": sum(entry.lineup_status == "landed" for entry in actions),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    entries = load_all_entries()
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "entries": entries[:50],
            "total": len(entries),
            **sidebar,
        },
    )


@app.get("/lineup", response_class=HTMLResponse)
def lineup_page(request: Request, session: str | None = Query(default=None)):
    entries = load_all_entries()
    selected_session = _slugify(session or "") if session else ""
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "lineup.html",
        {
            "selected_session": selected_session,
            "lineup_cadences": LINEUP_CADENCES,
            **_lineup_context(entries, selected_session),
            **sidebar,
        },
    )


@app.post("/lineup/new")
async def create_lineup_item(request: Request):
    form = await _read_form(request)
    title = str(form.get("title", "")).strip()
    if not title:
        return HTMLResponse("An action needs a title", status_code=400)
    session_raw = str(form.get("session", "")).strip()
    session = _slugify(session_raw) if session_raw else ""
    session_rows = session_stats(load_all_entries())
    session_row = next((row for row in session_rows if row["key"] == session), None)
    session_label = session_row["label"] if session_row else ""
    lineup_kind = str(form.get("lineup_kind", "action")).strip().lower()
    lineup_kind = lineup_kind if lineup_kind in {"action", "standard_work"} else "action"
    cadence = str(form.get("cadence", "once")).strip().lower()
    cadence = cadence if cadence in LINEUP_CADENCES else "once"
    if lineup_kind == "standard_work" and cadence == "once":
        cadence = "weekly"
    due_date = str(form.get("due_date", "")).strip()
    body = f"# {title}\n\n## Summary\n\n{str(form.get('details', '')).strip() or title}\n"
    folder = _notes_folder()
    entry_date = date.today().isoformat()
    path = folder / f"{entry_date}-{_slugify(title)}.md"
    counter = 2
    while path.exists():
        path = folder / f"{entry_date}-{_slugify(title)}-{counter}.md"
        counter += 1
    _write_entry(
        path, title, entry_date, "action", session, session_label, "active",
        [], ["Standard Work"] if lineup_kind == "standard_work" else [], [],
        "active", "lineup", body,
        lineup_status="open", lineup_kind=lineup_kind,
        owner=str(form.get("owner", "")), due_date=due_date, cadence=cadence,
    )
    suffix = f"?{urlencode({'session': session})}" if session else ""
    return RedirectResponse(url=f"/lineup{suffix}", status_code=303)


@app.post("/lineup/toggle/{file_id:path}")
async def toggle_lineup_item(request: Request, file_id: str):
    entry = find_entry_by_id(file_id)
    if entry is None or entry.entry_type != "action":
        return HTMLResponse("Action item not found", status_code=404)
    form = await _read_form(request)
    post = frontmatter.load(entry.path, encoding="utf-8")
    today = date.today().isoformat()
    if entry.lineup_kind == "standard_work" and entry.cadence != "once":
        if entry.last_completed == today:
            post.metadata["last_completed"] = ""
            post.metadata["due_date"] = today
        else:
            post.metadata["last_completed"] = today
            post.metadata["due_date"] = _next_due_date(entry.due_date, entry.cadence)
        post.metadata["lineup_status"] = "open"
    else:
        landed = entry.lineup_status != "landed"
        post.metadata["lineup_status"] = "landed" if landed else "open"
        post.metadata["last_completed"] = today if landed else ""
    _write_note(entry.path, post)
    return_to = str(form.get("return_to", "/lineup")).strip()
    if not return_to.startswith("/") or return_to.startswith("//"):
        return_to = "/lineup"
    return RedirectResponse(url=return_to, status_code=303)


@app.post("/lineup/promote/{file_id:path}")
async def promote_captured_action(request: Request, file_id: str):
    source_entry = find_entry_by_id(file_id)
    if source_entry is None:
        return HTMLResponse("Source note not found", status_code=404)
    form = await _read_form(request)
    fingerprint = str(form.get("fingerprint", "")).strip()
    action = next((item for item in _embedded_actions(source_entry) if item["fingerprint"] == fingerprint), None)
    if action is None:
        return HTMLResponse("Captured action not found", status_code=404)
    if any(entry.captured_from == action["captured_from"] for entry in load_all_entries()):
        return RedirectResponse(url="/lineup", status_code=303)
    title = action["text"]
    entry_date = date.today().isoformat()
    folder = _notes_folder()
    path = folder / f"{entry_date}-{_slugify(title)}.md"
    counter = 2
    while path.exists():
        path = folder / f"{entry_date}-{_slugify(title)}-{counter}.md"
        counter += 1
    body = f"# {title}\n\n## Summary\n\nCaptured in [{source_entry.title}](/entry/{source_entry.file_id}).\n"
    _write_entry(
        path, title, entry_date, "action", source_entry.session, source_entry.session_display if source_entry.session else "",
        source_entry.session_status, [], list(source_entry.themes),
        [{"type": "references", "target": source_entry.file_id, "note": "Captured as #A in source note"}],
        "active", "lineup", body, lineup_status="open", lineup_kind="action",
        captured_from=action["captured_from"],
    )
    suffix = f"?{urlencode({'session': source_entry.session})}" if source_entry.session else ""
    return RedirectResponse(url=f"/lineup{suffix}", status_code=303)


@app.get("/new", response_class=HTMLResponse)
def new_note(
    request: Request,
    session: str | None = Query(default=None),
    session_label: str | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    title: str | None = Query(default=None),
    summary: str | None = Query(default=None),
    body: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    source: str | None = Query(default=None),
):
    note_title = title or ""
    note_summary = summary or ""
    current_status = "active"
    current_source = source or "manual note"
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "note_form.html",
        {
            "mode": "new",
            "action": "/new",
            "title": note_title,
            "entry_date": date.today().isoformat(),
            "entry_type": _clean_entry_type(entry_type or "note"),
            "session": _slugify(session or "") if session else "",
            "session_label": session_label or "",
            "session_status": "active",
            "tags": tags or "",
            "themes": "",
            "note_themes": "",
            "relationships": "",
            "status": current_status,
            "source": current_source,
            "status_options": _options_with_current(STATUS_OPTIONS, current_status),
            "source_options": _options_with_current(SOURCE_OPTIONS, current_source),
            "summary": note_summary,
            # New notes start empty; the markdown scaffold is shown as a
            # placeholder and applied server-side only if the note is saved
            # with no content. Prefilled bodies (e.g. Spotter handoffs) pass
            # through unchanged.
            "body": body or "",
            "lineup_status": "open",
            "lineup_kind": "action",
            "owner": "",
            "due_date": "",
            "cadence": "once",
            "lineup_cadences": LINEUP_CADENCES,
            "whisper_models": WHISPER_MODELS,
            "transcription_model": _load_settings().get("transcription_model", "base"),
            **sidebar,
        },
    )


@app.post("/new")
async def create_note(request: Request):
    form = await _read_form(request)
    title = str(form.get("title", "")).strip() or "Untitled"
    entry_date = str(form.get("entry_date", "")).strip() or date.today().isoformat()
    entry_type = _clean_entry_type(str(form.get("entry_type", "")))
    session_raw = str(form.get("session", "")).strip()
    session_label = str(form.get("session_label", "")).strip()
    session = _slugify(session_raw) if session_raw else (_slugify(session_label) if session_label else "")
    session_status = str(form.get("session_status", "")).strip() or "active"
    tags = _coerce_csv(str(form.get("tags", "")))
    themes = _coerce_theme_csv(str(form.get("themes", "")))
    relationships = _parse_relationship_lines(str(form.get("relationships", "")))
    status = str(form.get("status", "")).strip().lower()
    status = status if status in STATUS_OPTIONS else "active"
    source = str(form.get("source", "")).strip() or "manual note"
    body = str(form.get("body", "")).strip() or _default_note_body(title)
    lineup_status = str(form.get("lineup_status", "open")).strip().lower()
    lineup_kind = str(form.get("lineup_kind", "action")).strip().lower()
    cadence = str(form.get("cadence", "once")).strip().lower()

    folder = _notes_folder()
    base_name = f"{entry_date}-{_slugify(title)}.md"
    path = folder / base_name
    counter = 2
    while path.exists():
        path = folder / f"{entry_date}-{_slugify(title)}-{counter}.md"
        counter += 1

    _write_entry(
        path,
        title,
        entry_date,
        entry_type,
        session,
        session_label,
        session_status,
        tags,
        themes,
        relationships,
        status,
        source,
        body,
        lineup_status=lineup_status,
        lineup_kind=lineup_kind,
        owner=str(form.get("owner", "")),
        due_date=str(form.get("due_date", "")),
        cadence=cadence,
    )
    file_id = path.relative_to(CONVERSATIONS).as_posix()
    return RedirectResponse(url=f"/entry/{file_id}", status_code=303)


@app.get("/sessions", response_class=HTMLResponse)
def sessions_page(request: Request):
    entries = load_all_entries()
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "sessions.html",
        {
            "session_rows": session_stats(entries),
            **sidebar,
        },
    )


@app.get("/trash", response_class=HTMLResponse)
def trash_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "trash.html", {
        **_sidebar_context(), "trash_items": vault_trash.items(SKATE_ROOT),
    })


async def _trash_confirmation(request: Request) -> dict:
    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@app.post("/api/trash/session/{session_key}")
async def trash_session(request: Request, session_key: str):
    payload = await _trash_confirmation(request)
    if payload.get("confirmed") is not True:
        return JSONResponse({"ok": False, "error": "Confirm the session removal first."}, status_code=400)
    with RECORDER_LOCK, vault_trash.LOCK:
        if (RECORDER.get("state") in {"recording", "stopping", "transcribing"}
                and (RECORDER.get("session") or "unassigned") == session_key):
            return JSONResponse({"ok": False, "error": "Finish recording and let the transcript save before moving this session to Trash."}, status_code=409)
        entries = load_all_entries()
        current = next((row for row in session_stats(entries) if row["key"] == session_key), None)
        if current is None:
            return JSONResponse({"ok": False, "error": "Session not found. Refresh the page."}, status_code=404)
        selected = [entry for entry in entries if entry.session_key == session_key]
        if payload.get("expected_count") != len(selected):
            return JSONResponse({"ok": False, "error": "The session's notes changed. Refresh the page and review the new count before removing it."}, status_code=409)
        paths = [entry.path for entry in selected]
        # Membership comes from metadata, not folder names: manual and imported
        # notes can share a folder while belonging to different sessions.
        for path in SESSIONS.rglob("*.md"):
            try:
                post = frontmatter.load(path, encoding="utf-8")
            except Exception:
                continue
            key = str(post.metadata.get("session", "") or path.parent.name or path.stem).strip()
            if key == session_key:
                paths.append(path)
        try:
            batch = vault_trash.move(SKATE_ROOT, paths, title=current["label"], kind="session", session=session_key)
        except (OSError, ValueError):
            return JSONResponse({"ok": False, "error": "The session could not be moved completely. Refresh the page and check Trash; your files remain on this PC."}, status_code=409)
    return {"ok": True, "redirect": "/trash", "id": batch["id"]}


@app.post("/api/trash/note/{file_id:path}")
async def trash_note(request: Request, file_id: str):
    payload = await _trash_confirmation(request)
    if payload.get("confirmed") is not True:
        return JSONResponse({"ok": False, "error": "Confirm the note removal first."}, status_code=400)
    with vault_trash.LOCK:
        # Only markdown notes can be removed through this endpoint, never keys
        # or shared attachments accepted by the older generic entry reader.
        if not file_id.endswith(".md"):
            return JSONResponse({"ok": False, "error": "Note not found."}, status_code=404)
        entry = find_entry_by_id(file_id)
        if entry is None:
            return JSONResponse({"ok": False, "error": "Note not found. Refresh the page."}, status_code=404)
        try:
            batch = vault_trash.move(SKATE_ROOT, [entry.path], title=entry.title, kind="note", session=entry.session_key)
        except (OSError, ValueError):
            return JSONResponse({"ok": False, "error": "The note could not be moved. Refresh the page and check Trash; your files remain on this PC."}, status_code=409)
    return {"ok": True, "redirect": "/session/" + quote(entry.session_key, safe="") + "?trashed=1", "id": batch["id"]}


@app.post("/api/trash/restore/{batch_id}")
def restore_trash(batch_id: str):
    try:
        restored = vault_trash.restore(SKATE_ROOT, batch_id)
    except vault_trash.TrashError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except OSError:
        return JSONResponse({"ok": False, "error": "Restore could not finish. Check the vault folder is writable, then try again."}, status_code=409)
    return {"ok": True, "redirect": "/session/" + quote(restored["session"], safe="")}


@app.get("/sessions/new", response_class=HTMLResponse)
def new_session(request: Request):
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "session_form.html",
        {
            "title": "",
            "session": "",
            "status": "active",
            "summary": "",
            **sidebar,
        },
    )


@app.post("/sessions/new")
async def create_session(request: Request):
    form = await _read_form(request)
    title = str(form.get("title", "")).strip() or "Untitled Session"
    session = _slugify(str(form.get("session", "")).strip() or title)
    status = str(form.get("status", "")).strip() or "active"
    summary = str(form.get("summary", "")).strip()

    folder = SESSIONS / session
    path = folder / "README.md"
    metadata = {
        "title": title,
        "session": session,
        "status": status,
        "date": date.today().isoformat(),
    }
    body = f"# {title}\n\n## Focus\n\n{summary or 'What are we trying to learn or decide?'}\n\n## Readout Notes\n\n- \n"
    folder.mkdir(parents=True, exist_ok=True)
    _write_note(path, frontmatter.Post(body, **metadata))
    return RedirectResponse(url=f"/session/{session}", status_code=303)


@app.post("/api/sessions")
async def create_session_inline(request: Request):
    """Create a session from a capture page without navigating or replacing one."""
    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Enter a session name."}, status_code=400)
    title = payload.get("title") if isinstance(payload, dict) else None
    if not isinstance(title, str) or not title.strip():
        return JSONResponse({"ok": False, "error": "Enter a session name."}, status_code=400)
    title = " ".join(title.split())
    if len(title) > 120 or not re.search(r"[A-Za-z0-9]", title):
        return JSONResponse({"ok": False, "error": "Use a name of up to 120 characters containing a letter or number."}, status_code=400)
    key = _slugify(title)
    if key == "unassigned":
        return JSONResponse({"ok": False, "error": "Unassigned is reserved. Choose a name for your new session."}, status_code=400)
    if re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", key):
        key = "session-" + key
    existing = next((row for row in session_stats(load_all_entries()) if row["key"] == key), None)
    if existing:
        if existing["status"] == "inactive":
            return JSONResponse({"ok": False, "error": "That session is inactive. Reactivate it on the Sessions page or choose another name."}, status_code=409)
        if existing["label"].casefold() != title.casefold():
            return JSONResponse({"ok": False, "error": "A session with a similar name already exists. Choose another name."}, status_code=409)
        return {"ok": True, "created": False, "session": {"key": key, "label": existing["label"]}}
    path = SESSIONS / key / "README.md"
    post = frontmatter.Post(
        f"# {title}\n\n## Focus\n\nWhat are we trying to learn or decide?\n\n## Readout Notes\n\n- \n",
        title=title, session=key, status="active", date=date.today().isoformat(),
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects a session created in another window.
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(frontmatter.dumps(post))
    except FileExistsError:
        return JSONResponse({"ok": False, "error": "That session already exists. Refresh the session list or choose another name."}, status_code=409)
    except OSError:
        return JSONResponse({"ok": False, "error": "The session could not be saved. Check that your vault folder is writable and try again."}, status_code=500)
    return JSONResponse({"ok": True, "created": True, "session": {"key": key, "label": title}}, status_code=201)


def _ensure_session(session_slug: str, session_label: str, summary: str = "") -> None:
    """Create a session README if it does not already exist (idempotent)."""
    if not session_slug:
        return
    folder = SESSIONS / session_slug
    path = folder / "README.md"
    if path.exists():
        return
    metadata = {
        "title": session_label or session_slug.replace("-", " ").title(),
        "session": session_slug,
        "status": "active",
        "date": date.today().isoformat(),
    }
    focus = summary or "Imported from Microsoft OneNote."
    body = f"# {metadata['title']}\n\n## Focus\n\n{focus}\n\n## Readout Notes\n\n- \n"
    folder.mkdir(parents=True, exist_ok=True)
    _write_note(path, frontmatter.Post(body, **metadata))


@app.get("/session/{session_key}", response_class=HTMLResponse)
def session_page(request: Request, session_key: str):
    all_entries = load_all_entries()
    entries = filter_entries(all_entries, session=session_key)
    rows = session_stats(all_entries)
    current = next((row for row in rows if row["key"] == session_key), None)
    if current is None and session_key == "unassigned":
        current = {"key": "unassigned", "label": "Unassigned", "status": "", "count": len(entries), "types": {}}
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "session.html",
        {
            "session": current or {"key": session_key, "label": session_key.replace("-", " ").title(), "status": "", "count": len(entries)},
            "entries": entries,
            **_lineup_context(all_entries, session_key),
            **sidebar,
        },
    )


@app.post("/session/{session_key}/status")
async def update_session_status(request: Request, session_key: str):
    form = await _read_form(request)
    session = _slugify(session_key)
    status = str(form.get("status", "")).strip().lower()
    if status not in SESSION_STATUS_OPTIONS:
        return HTMLResponse("Invalid session status", status_code=400)

    path = SESSIONS / session / "README.md"
    if path.exists():
        post = frontmatter.load(path, encoding="utf-8")
    else:
        rows = session_stats(load_all_entries())
        current = next((row for row in rows if row["key"] == session), None)
        title = current["label"] if current else session.replace("-", " ").title()
        body = f"# {title}\n\n## Focus\n\nWhat are we trying to learn or decide?\n"
        post = frontmatter.Post(body, title=title, session=session, date=date.today().isoformat())

    post.metadata["status"] = status
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_note(path, post)

    if str(form.get("return_to", "")).strip() == "sessions":
        return RedirectResponse(url="/sessions", status_code=303)
    return RedirectResponse(url=f"/session/{session}", status_code=303)


@app.post("/api/sessions/{session_key}/review-connections")
async def review_session_connections(session_key: str):
    session = _slugify(session_key)
    entries = _active_session_entries(session)
    if not entries:
        return JSONResponse(
            {"ok": False, "error": "This session has no active notes to review."},
            status_code=404,
        )
    label = entries[0].session_display or session.replace("-", " ").title()
    fallback = _local_connection_review(entries)
    settings = _load_settings()
    if not _llm_available(settings):
        review = _normalize_connection_review(fallback, entries, mode="local")
        return {
            "ok": True,
            "review": review,
            "session": session,
            "session_label": label,
            "note_count": len(entries),
            "message": f"{_llm_unavailable_reason(settings)}, so SKATE completed a local metadata audit. Semantic evidence links require an AI provider.",
        }
    try:
        response_text = _call_llm(settings, _connection_review_prompt(label, entries))
        raw = _extract_json_object(response_text)
        review = _normalize_connection_review(raw, entries, mode="ai")
        return {
            "ok": True,
            "review": review,
            "session": session,
            "session_label": label,
            "note_count": len(entries),
            "message": f"Reviewed {len(entries)} active notes with {_active_model(settings)}. Select the proposals you want SKATE to apply.",
        }
    except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as exc:
        review = _normalize_connection_review(fallback, entries, mode="local")
        return {
            "ok": True,
            "review": review,
            "session": session,
            "session_label": label,
            "note_count": len(entries),
            "message": f"AI review failed, so SKATE completed a local metadata audit. {exc}",
        }


@app.post("/api/sessions/{session_key}/apply-connections")
async def apply_session_connections(request: Request, session_key: str):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Could not read the selected proposals."}, status_code=400)

    session = _slugify(session_key)
    entries = _active_session_entries(session)
    if not entries:
        return JSONResponse(
            {"ok": False, "error": "This session has no active notes to update."},
            status_code=404,
        )
    raw = {
        "metadata": payload.get("metadata", []),
        "relationships": payload.get("relationships", []),
    }
    review = _normalize_connection_review(raw, entries, mode="approved")
    by_id = {entry.file_id: entry for entry in entries}
    changed_files = set()
    metadata_count = 0
    relationship_count = 0

    for suggestion in review["metadata"]:
        entry = by_id[suggestion["file_id"]]
        post = frontmatter.load(entry.path, encoding="utf-8")
        post.metadata["type"] = suggestion["entry_type"]
        post.metadata["themes"] = suggestion["themes"]
        post.metadata["tags"] = suggestion["tags"]
        _write_note(entry.path, post)
        changed_files.add(entry.file_id)
        metadata_count += 1

    # Reload changed notes so relationship application preserves metadata edits.
    entries = _active_session_entries(session)
    by_id = {entry.file_id: entry for entry in entries}
    for suggestion in review["relationships"]:
        source = by_id.get(suggestion["source"])
        if source is None:
            continue
        post = frontmatter.load(source.path, encoding="utf-8")
        relationships = post.metadata.get("relationships", [])
        if not isinstance(relationships, list):
            relationships = []
        relationships.append(
            {
                "type": suggestion["type"],
                "target": suggestion["target"],
                "note": suggestion["note"],
            }
        )
        post.metadata["relationships"] = relationships
        _write_note(source.path, post)
        changed_files.add(source.file_id)
        relationship_count += 1

    return {
        "ok": True,
        "metadata_applied": metadata_count,
        "relationships_applied": relationship_count,
        "files_updated": len(changed_files),
        "message": f"Applied {metadata_count} metadata update(s) and {relationship_count} evidence connection(s).",
    }


# ------------------------------------------------------------- attachments
# Pasted screenshots and attached files live beside the notes that reference
# them: conversations/<session>/attachments/. Notes link to them with relative
# Markdown (![name](attachments/x.png)), which renders here AND in Obsidian,
# and the whole folder stays portable - the vault remains plain files.

ATTACHMENTS_DIR_NAME = "attachments"
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
IMAGE_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# ".md" is deliberately NOT allowed: the vault loader treats every .md under
# conversations/ as a note, so an attached one would appear as a phantom entry.
ALLOWED_ATTACHMENT_EXTENSIONS = IMAGE_ATTACHMENT_EXTENSIONS | {
    ".pdf", ".csv", ".txt", ".docx", ".xlsx", ".pptx", ".zip",
}


def _attachment_dir(session: str) -> Path:
    slug = _slugify(session) or "unassigned"
    return CONVERSATIONS / slug / ATTACHMENTS_DIR_NAME


@app.post("/api/attachments")
async def upload_attachment(request: Request, session: str = "", filename: str = ""):
    """Save one pasted or attached file into the session's attachments folder.

    The request body is the raw file bytes - the same no-multipart pattern the
    transcription endpoints use, so no new dependency is required. Returns the
    relative Markdown snippet the note should insert.
    """
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED_ATTACHMENT_EXTENSIONS))
        return JSONResponse(
            {"ok": False, "error": f"That file type is not supported. Allowed: {allowed}."},
            status_code=400,
        )
    data = await request.body()
    if not data:
        return JSONResponse({"ok": False, "error": "The file was empty."}, status_code=400)
    if len(data) > MAX_ATTACHMENT_BYTES:
        limit_mb = MAX_ATTACHMENT_BYTES // (1024 * 1024)
        return JSONResponse(
            {"ok": False, "error": f"The file is larger than {limit_mb} MB."},
            status_code=400,
        )
    directory = _attachment_dir(session)
    directory.mkdir(parents=True, exist_ok=True)
    stem = _slugify(Path(filename).stem) or "attachment"
    target = directory / f"{stem}{extension}"
    counter = 2
    while target.exists():
        target = directory / f"{stem}-{counter}{extension}"
        counter += 1
    target.write_bytes(data)
    relative = f"{ATTACHMENTS_DIR_NAME}/{target.name}"
    if extension in IMAGE_ATTACHMENT_EXTENSIONS:
        markdown_snippet = f"![{target.stem}]({relative})"
    else:
        markdown_snippet = f"[{target.name}]({relative})"
    return JSONResponse({"ok": True, "path": relative, "markdown": markdown_snippet})


@app.get("/entry/{session}/attachments/{filename}")
def serve_attachment(session: str, filename: str):
    """Serve an attachment so the relative links inside notes resolve.

    Registered before the catch-all /entry/{file_id:path} route so it wins.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        return HTMLResponse("Not found", status_code=404)
    extension = Path(filename).suffix.lower()
    # Recorder WAVs may exceed the ordinary upload limit and are written locally.
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS | {".wav"}:
        return HTMLResponse("Not found", status_code=404)
    directory = _attachment_dir(session)
    try:
        target = (directory / filename).resolve()
        root = directory.resolve()
    except OSError:
        return HTMLResponse("Not found", status_code=404)
    if root not in target.parents or not target.is_file():
        return HTMLResponse("Not found", status_code=404)
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    headers = {}
    if extension not in IMAGE_ATTACHMENT_EXTENSIONS and extension != ".pdf":
        headers["Content-Disposition"] = f'attachment; filename="{target.name}"'
    return FileResponse(target, media_type=media_type, headers=headers)


def _render_note_html(entry) -> str:
    render_body = re.sub(
        r"(?im)^(\s*)(?:[-*]\s+)?\\?#\s*([POAQRSI])(?:\s*:|\s+)",
        r"\1- \\#\2: ", entry.body,
    )
    lines = []
    for line in render_body.splitlines():
        if re.match(r"^\s*-\s+\\#[POAQRSI]:", line) and lines and lines[-1].strip() and not re.match(r"^\s*-\s+", lines[-1]):
            lines.append("")
        lines.append(line)
    render_body = "\n".join(lines)
    # Absolute attachment URLs also work in session print views.
    render_body = re.sub(r"\]\(attachments/", f"](/entry/{entry.session_key}/attachments/", render_body)
    return _decorate_capture_markers(markdown.markdown(render_body, extensions=["fenced_code", "tables", "sane_lists"]))


@app.get("/session/{session_key}/print", response_class=HTMLResponse)
def print_session(request: Request, session_key: str):
    entries = _active_session_entries(session_key)
    if not entries:
        return HTMLResponse("There are no active notes to export in this session.", status_code=404)
    label = next((row["label"] for row in session_stats(load_all_entries()) if row["key"] == session_key), session_key)
    return TEMPLATES.TemplateResponse(request, "session_print.html", {
        "title": label, "session_key": session_key, "export_date": date.today().isoformat(),
        "notes": [{"entry": entry, "html": _render_note_html(entry)} for entry in entries],
    })


@app.get("/entry/{file_id:path}", response_class=HTMLResponse)
def view_entry(request: Request, file_id: str):
    entry = find_entry_by_id(file_id)
    if entry is None:
        return HTMLResponse("Entry not found", status_code=404)
    body_html = _render_note_html(entry)
    embedded_actions = _embedded_actions(entry) if entry.entry_type != "action" else []
    promoted_sources = {candidate.captured_from for candidate in load_all_entries() if candidate.captured_from}
    for action in embedded_actions:
        action["promoted"] = action["captured_from"] in promoted_sources
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "entry.html",
        {
            "entry": entry,
            "body_html": body_html,
            "embedded_actions": embedded_actions,
            "lineup_today": date.today().isoformat(),
            **sidebar,
        },
    )


@app.get("/edit/{file_id:path}", response_class=HTMLResponse)
def edit_entry(request: Request, file_id: str):
    entry = find_entry_by_id(file_id)
    if entry is None:
        return HTMLResponse("Entry not found", status_code=404)
    current_status = "inactive" if entry.status.strip().lower() == "inactive" else "active"
    current_source = entry.source or "manual note"
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "note_form.html",
        {
            "mode": "edit",
            "action": f"/edit/{entry.file_id}",
            "title": entry.title,
            "entry_date": entry.date or date.today().isoformat(),
            "entry_type": entry.entry_type,
            "session": entry.session,
            "session_label": entry.session_label,
            "session_status": entry.session_status or "active",
            "tags": ", ".join(entry.tags),
            "themes": ", ".join(entry.themes),
            "note_themes": ", ".join(entry.themes),
            "relationships": _relationship_lines(entry.relationships),
            "status": current_status,
            "source": current_source,
            "status_options": _options_with_current(STATUS_OPTIONS, current_status),
            "source_options": _options_with_current(SOURCE_OPTIONS, current_source),
            "summary": entry.summary,
            "body": entry.body,
            "entry": entry,
            "lineup_status": entry.lineup_status or "open",
            "lineup_kind": entry.lineup_kind,
            "owner": entry.owner,
            "due_date": entry.due_date,
            "cadence": entry.cadence,
            "lineup_cadences": LINEUP_CADENCES,
            "whisper_models": WHISPER_MODELS,
            "transcription_model": _load_settings().get("transcription_model", "base"),
            **sidebar,
        },
    )


@app.post("/edit/{file_id:path}")
async def update_entry(request: Request, file_id: str):
    entry = find_entry_by_id(file_id)
    if entry is None:
        return HTMLResponse("Entry not found", status_code=404)

    form = await _read_form(request)
    title = str(form.get("title", "")).strip() or "Untitled"
    entry_date = str(form.get("entry_date", "")).strip() or date.today().isoformat()
    entry_type = _clean_entry_type(str(form.get("entry_type", "")))
    session_raw = str(form.get("session", "")).strip()
    session_label = str(form.get("session_label", "")).strip()
    session = _slugify(session_raw) if session_raw else (_slugify(session_label) if session_label else "")
    session_status = str(form.get("session_status", "")).strip() or "active"
    tags = _coerce_csv(str(form.get("tags", "")))
    themes = _coerce_theme_csv(str(form.get("themes", "")))
    relationships = _parse_relationship_lines(str(form.get("relationships", "")))
    status = str(form.get("status", "")).strip().lower()
    status = status if status in STATUS_OPTIONS else "active"
    source = str(form.get("source", "")).strip() or "manual note"
    body = str(form.get("body", "")).strip() or _default_note_body(title)
    lineup_status = str(form.get("lineup_status", entry.lineup_status or "open")).strip().lower()
    lineup_kind = str(form.get("lineup_kind", entry.lineup_kind)).strip().lower()
    cadence = str(form.get("cadence", entry.cadence)).strip().lower()

    _write_entry(
        entry.path,
        title,
        entry_date,
        entry_type,
        session,
        session_label,
        session_status,
        tags,
        themes,
        relationships,
        status,
        source,
        body,
        lineup_status=lineup_status,
        lineup_kind=lineup_kind,
        owner=str(form.get("owner", entry.owner)),
        due_date=str(form.get("due_date", entry.due_date)),
        cadence=cadence,
        last_completed=entry.last_completed,
        captured_from=entry.captured_from,
    )
    return RedirectResponse(url=f"/entry/{entry.file_id}", status_code=303)


@app.post("/api/classify-note")
async def classify_note(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the note text."}

    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()
    fallback = _local_metadata_suggestion(title, body)
    settings = _load_settings()
    if not _llm_available(settings):
        return {
            "ok": True,
            "suggestion": fallback,
            "message": f"{_llm_unavailable_reason(settings)}, so SKATE used a local suggestion.",
        }

    try:
        response_text = _call_llm(settings, _classification_prompt(title, body))
        raw = _extract_json_object(response_text)
        suggestion = _normalize_metadata_suggestion(raw, fallback)
        suggestion["provider"] = settings["provider"]
        suggestion["model"] = settings["model"]
        return {"ok": True, "suggestion": suggestion}
    except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
        return {
            "ok": True,
            "suggestion": fallback,
            "message": f"AI classification failed, so SKATE used a local suggestion. {e}",
        }


CLEANUP_CLOUD_SLOTS = threading.BoundedSemaphore(3)
CLEANUP_LOCAL_SLOTS = threading.BoundedSemaphore(1)


class CleanupCancelled(Exception):
    pass


def _cleanup_model_call(settings: dict, prompt: str, cancelled: threading.Event, provider_stopped: threading.Event) -> str:
    # Hold the permit inside the real request thread. Cancelling its async
    # caller cannot release a slot while a provider request is still running.
    slots = CLEANUP_LOCAL_SLOTS if settings.get("provider") == "lmstudio" else CLEANUP_CLOUD_SLOTS
    while not cancelled.is_set() and not provider_stopped.is_set():
        if not slots.acquire(timeout=0.1):
            continue
        try:
            if cancelled.is_set() or provider_stopped.is_set():
                break
            return _call_llm(settings, prompt)
        finally:
            slots.release()
    raise CleanupCancelled()


async def _reviewed_summary(payload: dict, kind: str, progress=None, cancelled=None) -> dict:
    title = str(payload.get("title", "")).strip() or "Untitled"
    source = str(payload.get("body" if kind == "compression" else "transcript", "")).strip()
    if not source:
        return {"ok": False, "error": "Add note or transcript text first."}
    focus = " ".join(str(payload.get(key, "")) for key in ("title", "tags", "focus", "session_label"))
    review = note_quality.screen(source, focus)
    settings = _load_settings()
    excluded_topics, failures, completed, active = [], 0, 0, 0
    connection_failures = 0
    provider_issue = ""
    cancelled = cancelled or threading.Event()
    provider_stopped = threading.Event()
    ai = _llm_available(settings)
    parts = note_quality.chunks(review["text"]) if ai else ([review["text"]] if review["text"] else [])
    results = [None] * len(parts)
    pending = iter(enumerate(parts))
    workers_count = min(len(parts), 3 if ai and settings.get("provider") != "lmstudio" else 1)

    def report():
        if progress:
            progress({"type": "progress", "completed": completed, "total": len(parts),
                      "active": active, "fallback_sections": failures,
                      "provider": LLM_PROVIDER_LABELS.get(settings["provider"], settings["provider"]) if ai else "Local cleanup",
                      "provider_issue": provider_issue})

    async def worker():
        nonlocal completed, active, failures, connection_failures, provider_issue
        for index, part in pending:
            if cancelled.is_set():
                raise asyncio.CancelledError
            active += 1
            report()
            if kind == "compression":
                fallback = _local_note_compression(title, focus, part)
                prompt = _compression_prompt(title, focus, part)
                normalize = _normalize_compression
            else:
                fallback = _local_transcript_summary(focus, part)
                prompt = _transcript_summary_prompt(f"{title}\nWorkshop focus: {focus}", part)
                normalize = _normalize_transcript_summary
            result = fallback
            used_ai = False
            if ai and not provider_stopped.is_set():
                try:
                    response = await asyncio.to_thread(_cleanup_model_call, settings, prompt, cancelled, provider_stopped)
                    raw = _extract_json_object(response)
                    result = normalize(raw, fallback)
                    used_ai = True
                    labels = raw.get("excluded_topics", [])
                    if isinstance(labels, list):
                        excluded_topics.extend(label[:160] for label in labels if isinstance(label, str))
                except ModelHTTPError as exc:
                    # Do not repeat a rejected key, invalid model, quota error,
                    # or failing service once per section of a long meeting.
                    if exc.status_code in {401, 403}:
                        provider_issue = "The AI provider rejected access. Check the saved API key."
                    elif exc.status_code == 429:
                        provider_issue = "The AI provider reported a rate or quota limit."
                    else:
                        provider_issue = f"The AI provider rejected the request (HTTP {exc.status_code}). Check the provider and model settings."
                    provider_stopped.set()
                except (URLError, TimeoutError, OSError):
                    connection_failures += 1
                    if connection_failures >= 2:
                        provider_issue = "Repeated AI connection failures or timeouts. Remaining sections use local extraction."
                        provider_stopped.set()
                except (ValueError, KeyError, TypeError, HTTPError):
                    pass  # A malformed section falls back locally without losing its evidence.
                except CleanupCancelled:
                    if cancelled.is_set():
                        raise asyncio.CancelledError
            if ai and not used_ai:
                failures += 1
            # Completion order can vary. Merge by source order, never by speed.
            results[index] = note_quality.guard_result(result, focus)
            active -= 1
            completed += 1
            report()

    report()
    workers = [asyncio.create_task(worker()) for _ in range(workers_count)]
    try:
        await asyncio.gather(*workers)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    finally:
        if any(not task.done() for task in workers):
            cancelled.set()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
    empty = (_local_note_compression(title, focus, "") if kind == "compression"
             else _local_transcript_summary(title, ""))
    combined = dict(results[0] if results else empty)
    # Merge without a global six-signal cap that would discard late decisions.
    for key in ("key_points", *note_quality.SIGNAL_KEYS.values(), "tags"):
        combined[key] = list(dict.fromkeys(item for result in results for item in result.get(key, [])))
    for key in ("gist", "summary", "agent_memory"):
        if key in combined:
            combined[key] = "\n\n".join(dict.fromkeys(result.get(key, "") for result in results if result.get(key))) or empty.get(key, "")
    combined["mode"] = "mixed" if failures and failures < len(parts) else "ai" if ai and parts and not failures else "local"
    if ai and parts:
        combined["provider"], combined["model"] = settings["provider"], _active_model(settings)
    review.pop("text")
    review.pop("units")
    review.update({"chunks_processed": len(parts), "local_fallback_chunks": failures,
                   "excluded_topics": list(dict.fromkeys(excluded_topics)), "provider_issue": provider_issue})
    message = f"Reviewed all {review['source_units']} text segments. Removed {review['excluded_count']} clear off-topic segments and {review['duplicate_count']} duplicates."
    if combined["mode"] != "ai":
        message += " Local rules cannot judge every topic. Uncertain content is kept for review; No AI output puts it after the structured signals."
    if failures:
        message += f" AI was unavailable for {failures} sections; those sections use local extraction."
    if provider_issue:
        message += " " + provider_issue
    key = "compression" if kind == "compression" else "summary"
    render = _compression_markdown if kind == "compression" else _transcript_summary_markdown
    return {"ok": True, key: combined, "markdown": render(combined), "review": review, "message": message}


@app.post("/api/cleanup/stream")
async def stream_cleanup(request: Request):
    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Could not read the note text."}, status_code=400)
    if not isinstance(payload, dict) or payload.get("kind") not in {"compression", "summary"}:
        return JSONResponse({"ok": False, "error": "Choose note cleanup or transcript summary."}, status_code=400)

    async def events():
        queue = asyncio.Queue()
        cancelled = threading.Event()

        async def run():
            try:
                result = await _reviewed_summary(payload, payload["kind"], queue.put_nowait, cancelled)
                queue.put_nowait({"type": "result", "data": result})
            except Exception:
                queue.put_nowait({"type": "error", "error": "Cleanup could not finish. Your original note is still in the editor."})

        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    event = {"type": "heartbeat"}
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] in {"result", "error"}:
                    break
        finally:
            cancelled.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/compress-note")
async def compress_note(request: Request):
    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "Could not read the note text."}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Could not read the note text."}
    return await _reviewed_summary(payload, "compression")


def _perform_transcription(audio_bytes: bytes | Path, filename: str, content_type: str, requested_model: str, progress_callback=None) -> dict:
    def report(percent: int, phase: str) -> None:
        if progress_callback:
            progress_callback(percent, phase)

    settings = _load_settings()
    valid_whisper_models = {m["id"] for m in WHISPER_MODELS}
    model_name = requested_model if requested_model in valid_whisper_models else settings.get("transcription_model", "base")

    # Privacy guarantee: uploaded recordings are ALWAYS transcribed locally.
    # The speech_to_text_provider setting governs only Spotter Live's
    # realtime captions; recording audio never leaves this computer.
    try:
        with TRANSCRIPTION_RUN_LOCK:
            transcript = _local_whisper_transcribe(audio_bytes, filename, content_type, model_name, progress_callback=progress_callback)
        if not transcript:
            return {"ok": False, "error": "Local Whisper returned an empty transcript."}
        return {"ok": True, "transcript": transcript, "model": model_name, "mode": "local-whisper"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Local transcription failed. {e}"}


@app.post("/api/transcribe-audio")
async def transcribe_audio(request: Request):
    path = None
    try:
        upload_type = str(request.headers.get("content-type", "")).split(";", 1)[0].lower()
        if upload_type == "application/octet-stream":
            filename = unquote(request.headers.get("x-skate-filename", "recording.webm"))
            content_type = request.headers.get("x-skate-content-type", "") or mimetypes.guess_type(filename)[0] or "audio/webm"
            model = request.headers.get("x-skate-model", "")
            path = await receive_recording(request, _audio_upload_limit())
            source = path
        else:
            # Compatibility for short microphone clips in previously opened tabs.
            path = await receive_recording(request, 16 * 1024 * 1024, ".json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            filename = str(payload.get("filename", "recording.webm"))
            content_type = str(payload.get("content_type", "audio/webm"))
            model = str(payload.get("model", ""))
            encoded = str(payload.get("data", "")).split(",", 1)[-1]
            source = base64.b64decode(encoded, validate=True)
            if not source:
                raise UploadProblem("The recording file was empty.")
        return await asyncio.to_thread(_perform_transcription, source, filename, content_type, model)
    except UploadProblem as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=exc.status)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return JSONResponse({"ok": False, "error": "Could not read the recording upload."}, status_code=400)
    finally:
        if path:
            path.unlink(missing_ok=True)


def _update_transcription_job(job_id: str, **changes) -> None:
    with TRANSCRIPTION_JOBS_LOCK:
        job = TRANSCRIPTION_JOBS.get(job_id)
        if not job:
            return
        if "progress" in changes:
            changes["progress"] = max(int(job.get("progress", 0)), min(100, int(changes["progress"])))
        job.update(changes)
        job["updated_at"] = time.time()


def _run_transcription_job(job_id: str, audio_bytes: bytes | Path, filename: str, content_type: str, requested_model: str) -> None:
    def progress(percent: int, phase: str) -> None:
        _update_transcription_job(job_id, progress=percent, phase=phase, status="working")

    try:
        progress(1, "Preparing recording")
        result = _perform_transcription(audio_bytes, filename, content_type, requested_model, progress_callback=progress)
        if result.get("ok"):
            _update_transcription_job(
                job_id,
                status="complete",
                progress=100,
                phase="Transcript complete",
                transcript=result.get("transcript", ""),
                model=result.get("model", ""),
                mode=result.get("mode", ""),
            )
        else:
            _update_transcription_job(job_id, status="error", phase="Transcription stopped", error=result.get("error", "Transcription failed."))
    except Exception as exc:  # noqa: BLE001
        _update_transcription_job(job_id, status="error", phase="Transcription stopped", error=str(exc))
    finally:
        if isinstance(audio_bytes, Path):
            audio_bytes.unlink(missing_ok=True)


@app.post("/api/transcription-jobs")
async def start_transcription_job(request: Request):
    try:
        audio_bytes = await receive_recording(request, _audio_upload_limit())
    except UploadProblem as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=exc.status)
    filename = unquote(str(request.headers.get("x-skate-filename", "recording.webm"))).strip() or "recording.webm"
    content_type = str(request.headers.get("x-skate-content-type", "")).strip() or mimetypes.guess_type(filename)[0] or "audio/webm"
    requested_model = str(request.headers.get("x-skate-model", "")).strip()
    now = time.time()
    with TRANSCRIPTION_JOBS_LOCK:
        expired = [key for key, value in TRANSCRIPTION_JOBS.items() if value.get("status") in {"complete", "error"} and now - float(value.get("updated_at", now)) > 3600]
        for key in expired:
            TRANSCRIPTION_JOBS.pop(key, None)
        job_id = uuid.uuid4().hex
        TRANSCRIPTION_JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "phase": "Queued",
            "filename": filename,
            "created_at": now,
            "updated_at": now,
        }

    try:
        threading.Thread(
            target=_run_transcription_job,
            args=(job_id, audio_bytes, filename, content_type, requested_model),
            daemon=True,
            name=f"skate-transcription-{job_id[:8]}",
        ).start()
    except RuntimeError:
        audio_bytes.unlink(missing_ok=True)
        _update_transcription_job(job_id, status="error", error="The local transcription worker could not start.")
        return JSONResponse({"ok": False, "error": "The local transcription worker could not start. Try again."}, status_code=503)
    return {"ok": True, "job_id": job_id}


@app.get("/api/transcription-jobs/{job_id}")
async def transcription_job_status(job_id: str):
    with TRANSCRIPTION_JOBS_LOCK:
        job = TRANSCRIPTION_JOBS.get(job_id)
        if not job:
            return JSONResponse({"ok": False, "error": "That transcription job was not found."}, status_code=404)
        return {"ok": True, **dict(job)}


@app.get("/api/transcription-health")
async def transcription_health():
    import importlib.util

    model_root = _whisper_model_root()
    model_files = sorted(path.name for path in model_root.glob("*.pt"))
    # faster-whisper stores models as HuggingFace snapshot folders.
    fw_models = sorted(
        path.name.rsplit("faster-whisper-", 1)[-1]
        for path in model_root.glob("models--*faster-whisper-*")
        if path.is_dir()
    )
    has_faster_whisper = bool(importlib.util.find_spec("faster_whisper"))
    has_classic_whisper = bool(importlib.util.find_spec("whisper"))
    ffmpeg_path = _find_local_ffmpeg()
    return {
        "ok": True,
        "whisper": has_faster_whisper or has_classic_whisper,
        # faster-whisper decodes through bundled PyAV; classic whisper
        # needs the external ffmpeg helper.
        "decoder": has_faster_whisper or bool(ffmpeg_path),
        "decoder_path": str(ffmpeg_path) if ffmpeg_path else "",
        "model_root": str(model_root),
        "models": model_files + [name for name in fw_models if name not in model_files],
        "base_model": "base.pt" in model_files or "base" in fw_models,
        "engine": "faster-whisper" if has_faster_whisper else ("openai-whisper" if has_classic_whisper else ""),
        "frozen": bool(getattr(sys, "frozen", False)),
        "max_upload_bytes": _audio_upload_limit(),
    }


@app.post("/api/speak")
async def speak_api(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the text to speak."}

    text = str(payload.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "No text to speak."}

    settings = _load_settings()
    provider = settings.get("text_to_speech_provider")
    if provider == "openai":
        api_key = settings.get("api_keys", {}).get("openai", "")
        if not api_key:
            return {"ok": False, "error": "No OpenAI API key is saved."}
        try:
            audio = await _openai_realtime_speak(
                text[:5000],
                api_key,
                settings.get("openai_realtime_model", "gpt-realtime-mini"),
                settings.get("openai_realtime_voice", "marin"),
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, ImportError) as e:
            return {"ok": False, "error": f"OpenAI Realtime voice failed. {e}"}
        return Response(content=audio, media_type="audio/wav")
    if provider != "elevenlabs":
        return {"ok": False, "error": "Cloud speech is not the selected provider."}
    api_key = settings.get("api_keys", {}).get("elevenlabs", "")
    if not api_key:
        return {"ok": False, "error": "No ElevenLabs API key is saved."}

    try:
        audio = _elevenlabs_tts(
            text[:5000],
            api_key,
            settings.get("elevenlabs_voice_id", ""),
            settings.get("elevenlabs_tts_model", ""),
        )
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        return {"ok": False, "error": f"ElevenLabs TTS failed. {e}"}
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/elevenlabs-test")
async def elevenlabs_test(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}

    settings = _load_settings()
    api_key = str(payload.get("api_key", "")).strip() or settings.get("api_keys", {}).get("elevenlabs", "")
    if not api_key:
        return {"ok": False, "error": "Enter or save an ElevenLabs API key first."}
    voice_id = str(payload.get("voice_id", "")).strip() or settings.get("elevenlabs_voice_id", "") or "21m00Tcm4TlvDq8ikWAM"
    model_id = str(payload.get("model", "")).strip() or settings.get("elevenlabs_tts_model", "") or "eleven_flash_v2_5"
    text = str(payload.get("text", "")).strip() or "Spotter is online. ElevenLabs voice check complete."

    try:
        audio = _elevenlabs_tts(text[:300], api_key, voice_id, model_id)
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        return {"ok": False, "error": f"ElevenLabs test failed. {e}"}
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/api/voice-config")
async def voice_config():
    settings = _load_settings()
    return {
        "ok": True,
        "speak_aloud": bool(settings.get("speak_responses_aloud", False)),
        "tts_provider": settings.get("text_to_speech_provider", "local"),
        "microphone": settings.get("microphone", "system-default"),
        "stt_provider": settings.get("speech_to_text_provider", "local"),
        "openai_realtime_model": settings.get("openai_realtime_model", "gpt-realtime-mini"),
        "openai_realtime_transcription_model": settings.get("openai_realtime_transcription_model", "gpt-realtime-whisper"),
    }


@app.post("/api/elevenlabs-voices")
async def elevenlabs_voices(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}

    settings = _load_settings()
    api_key = str(payload.get("api_key", "")).strip() or settings.get("api_keys", {}).get("elevenlabs", "")
    if not api_key:
        return {"ok": False, "error": "Enter or save an ElevenLabs API key first."}
    try:
        voices = _elevenlabs_list_voices(api_key)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        return {"ok": False, "error": f"Could not load voices. {e}"}
    return {"ok": True, "voices": voices}


@app.post("/api/summarize-transcript")
async def summarize_transcript(request: Request):
    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "Could not read the transcript."}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Could not read the transcript."}
    return await _reviewed_summary(payload, "summary")


@app.get("/spotter", response_class=HTMLResponse)
def spotter_page(
    request: Request,
    session: str | None = Query(default=None),
    session_label: str | None = Query(default=None),
):
    sidebar = _sidebar_context()
    settings = _load_settings()
    entries = load_all_entries()
    rows = session_stats(entries)
    resolved_label = session_label or ""
    if session and not resolved_label:
        match = next((row for row in rows if row["key"] == session), None)
        resolved_label = match["label"] if match else session
    return TEMPLATES.TemplateResponse(
        request,
        "spotter.html",
        {
            "modes": SPOTTER_MODES,
            "whisper_models": WHISPER_MODELS,
            "transcription_model": settings.get("transcription_model", "base"),
            "spotter_name": settings.get("spotter_name", "Spotter"),
            "spotter_subtitle": settings.get("spotter_subtitle", "Workshop coach"),
            "current_session": session or "",
            "current_session_label": resolved_label,
            "session_rows": rows,
            "speak_aloud": settings.get("speak_responses_aloud", False),
            "tts_provider": settings.get("text_to_speech_provider", "local"),
            **sidebar,
        },
    )


@app.post("/api/spotter")
async def spotter_api(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the Spotter capture."}

    text = str(payload.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "Spotter needs a workshop capture to coach from."}

    mode = _spotter_mode(str(payload.get("mode", "")))
    session = str(payload.get("session", "")).strip()
    session_label = str(payload.get("session_label", "")).strip()
    review = note_quality.screen(text, session_label or session)
    text = review["text"]
    fallback = _local_spotter_response(mode, text, session_label or session)
    settings = _load_settings()
    result = fallback
    message = ""

    if text and _llm_available(settings):
        try:
            session_context = _spotter_session_context(session, text)
            response_text = await asyncio.to_thread(_call_llm, _feature_settings(settings, "spotter"), _spotter_prompt(mode, text, session_label or session, session_context, settings))
            result = _normalize_spotter_response(_extract_json_object(response_text), fallback, mode)
            result["provider"] = settings["provider"]
            result["model"] = _active_model(_feature_settings(settings, "spotter"))
        except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
            message = f"AI Spotter coaching failed, so SKATE used local coaching. {e}"
    else:
        message = f"{_llm_unavailable_reason(settings)}, so SKATE used local Spotter coaching."

    result = note_quality.guard_result(result, session_label or session)
    if not text:
        return {"ok": True, "result": result, "markdown": "", "create_url": "",
                "message": "Only off-topic conversation was found. Nothing was prepared for the vault."}
    markdown_body = _spotter_markdown(result)
    create_url = "/new?" + urlencode(
        {
            "title": result["title"],
            "entry_type": result["entry_type"],
            "summary": result["summary"],
            "body": markdown_body,
            "tags": ", ".join(_slugify(theme) for theme in result["themes"]),
            "source": f"spotter:{mode['id']}",
            "session": session,
            "session_label": session_label,
        }
    )
    return {
        "ok": True,
        "result": result,
        "markdown": markdown_body,
        "create_url": create_url,
        "message": message,
    }


# --- Spotter Live: always-on room transcription + transcript-aware agent ---

TRANSCRIPTS_DIR = SKATE_ROOT / "transcripts"


def _safe_transcript_path(name: str) -> Path | None:
    """Resolve a transcript filename inside TRANSCRIPTS_DIR, rejecting traversal."""
    clean = re.sub(r"[^A-Za-z0-9_.-]", "-", str(name).strip())
    if not clean or not clean.endswith(".md") or clean.startswith("."):
        return None
    path = (TRANSCRIPTS_DIR / clean).resolve()
    if path.parent != TRANSCRIPTS_DIR.resolve():
        return None
    return path


@app.get("/spotter-live", response_class=HTMLResponse)
def spotter_live_page(request: Request):
    sidebar = _sidebar_context()
    settings = _load_settings()
    stt_provider = settings.get("speech_to_text_provider", "local")
    if stt_provider not in {"local", "openai", "elevenlabs"}:
        stt_provider = "openai"
    return TEMPLATES.TemplateResponse(
        request,
        "spotter-live.html",
        {
            "modes": SPOTTER_MODES,
            "spotter_name": settings.get("spotter_name", "Spotter"),
            "speak_aloud": settings.get("speak_responses_aloud", False),
            "tts_provider": settings.get("text_to_speech_provider", "local"),
            "stt_provider": stt_provider,
            "microphone": settings.get("microphone", "system-default"),
            "elevenlabs_key_present": bool(settings.get("api_keys", {}).get("elevenlabs")),
            "openai_key_present": bool(settings.get("api_keys", {}).get("openai")),
            "openai_realtime_model": settings.get("openai_realtime_model", "gpt-realtime-mini"),
            "openai_realtime_transcription_model": settings.get("openai_realtime_transcription_model", "gpt-realtime-whisper"),
            **sidebar,
        },
    )


# ---------------------------------------------------------------------------
# Meeting recorder: capture what this PC hears (WASAPI loopback) plus the
# microphone, transcribe locally with Whisper, and save the result as a note.
# Runs server-side, so navigating away or hiding the desktop window in the
# tray does not stop it. Exit SKATE shuts down the server and recording. Works
# with any meeting app (Teams, Zoom, Meet, Webex) because it never touches
# the meeting itself: no tenant, no calendar, no bot joining the call.

RECORDER_SAMPLERATE = 16_000
RECORDER_CHUNK_SECONDS = 0.5
RECORDER_LOCK = threading.Lock()
RECORDER: dict = {"state": "idle"}


def _recorder_available() -> tuple[bool, str]:
    try:
        import soundcard  # noqa: F401
    except Exception as exc:
        return False, (
            "System-audio capture needs the 'soundcard' package. "
            "Run Start SKATE.bat once after updating (it installs new requirements), "
            f"or: pip install soundcard  ({exc.__class__.__name__})"
        )
    return True, ""


def _recorder_capture(kind: str, stop_event, chunks: list, errors: list) -> None:
    """Capture one stream (system loopback or microphone) until stopped."""
    try:
        import numpy as np
        import soundcard as sc

        if kind == "loopback":
            speaker = sc.default_speaker()
            source = sc.get_microphone(str(speaker.name), include_loopback=True)
        else:
            source = sc.default_microphone()
        frames = int(RECORDER_SAMPLERATE * RECORDER_CHUNK_SECONDS)
        with source.recorder(samplerate=RECORDER_SAMPLERATE, channels=1) as recorder:
            while not stop_event.is_set():
                data = recorder.record(numframes=frames)
                mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                chunks.append(
                    (mono * 32767.0).clip(-32768, 32767).astype(np.int16)
                )
    except Exception as exc:  # surfaced in status; the other stream continues
        errors.append(f"{kind}: {exc}")


def _recorder_wav_bytes(loopback_chunks: list, mic_chunks: list) -> bytes:
    """Mix the two int16 streams (sum with clipping) into mono WAV bytes."""
    import numpy as np

    def joined(chunks):
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)

    a, b = joined(loopback_chunks), joined(mic_chunks)
    total = max(len(a), len(b))
    if total == 0:
        return b""
    mixed = (
        np.pad(a.astype(np.int32), (0, total - len(a)))
        + np.pad(b.astype(np.int32), (0, total - len(b)))
    )
    mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RECORDER_SAMPLERATE)
        wav.writeframes(mixed.tobytes())
    return buffer.getvalue()


def _recorder_note_body(title: str, transcript: str, include_mic: bool, model_name: str, audio_filename: str = "") -> str:
    sources = "system audio + microphone" if include_mic else "system audio"
    stamp = time.strftime("%Y-%m-%d %H:%M")
    audio_link = (
        f"[Download recording (WAV)]({ATTACHMENTS_DIR_NAME}/{quote(audio_filename)})\n\n"
        if audio_filename else ""
    )
    return (
        f"# {title}\n\n"
        f"Recorded from {sources} on {stamp}. Transcribed locally with Whisper ({model_name}); "
        f"nothing left this computer.\n\n"
        f"{audio_link}"
        f"## Transcript\n\n{transcript.strip()}\n"
    )


def _recorder_save_audio(session: str, wav_bytes: bytes) -> Path:
    directory = _attachment_dir(session)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"recording-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:12]}.wav"
    path = directory / filename
    # Exclusive creation prevents a second recording from replacing an earlier one.
    with path.open("xb") as output:
        output.write(wav_bytes)
        output.flush()
        os.fsync(output.fileno())
    return path


def _recorder_save_note(session: str, session_label: str, body: str, title: str) -> str:
    slug = _slugify(session) or "unassigned"
    folder = CONVERSATIONS / slug
    entry_date = date.today().isoformat()
    path = folder / f"{entry_date}-{_slugify(title)}.md"
    counter = 2
    while path.exists():
        path = folder / f"{entry_date}-{_slugify(title)}-{counter}.md"
        counter += 1
    _write_entry(
        path, title, entry_date, "note", slug, session_label.strip(), "active",
        ["meeting-recording"], [], [], "active", "system recording", body,
    )
    return path.relative_to(CONVERSATIONS).as_posix()


def _recorder_finalize(include_mic: bool, session: str, session_label: str, model_name: str) -> None:
    state = RECORDER
    try:
        for thread in state.get("threads", []):
            thread.join(timeout=10)
        wav_bytes = _recorder_wav_bytes(state.get("loopback", []), state.get("mic", []))
        state["loopback"], state["mic"] = [], []
        if not wav_bytes:
            problems = "; ".join(state.get("errors", [])) or "no audio was captured"
            raise RuntimeError(problems)
        audio_path = _recorder_save_audio(session, wav_bytes)
        del wav_bytes
        audio_id = audio_path.relative_to(CONVERSATIONS).as_posix()
        state.update({"audio": audio_id, "audio_url": f"/entry/{audio_id}"})
        state["state"] = "transcribing"
        state["progress"] = 0

        def on_progress(percent, phase):
            state["progress"] = percent
            state["phase"] = phase

        transcript = _faster_whisper_transcribe(
            audio_path, audio_path.name, "audio/wav", model_name, on_progress
        )
        title = f"Meeting recording {time.strftime('%Y-%m-%d %H:%M')}"
        body = _recorder_note_body(title, transcript or "(no speech detected)", include_mic, model_name, audio_path.name)
        file_id = _recorder_save_note(session, session_label, body, title)
        state.update({"state": "saved", "note": file_id, "url": f"/entry/{file_id}"})
    except Exception as exc:
        rescue = ""
        try:
            if state.get("audio"):
                rescue = f" The audio is saved as {Path(state['audio']).name} in the session's attachments. Download it below to retry transcription."
            errors = "; ".join(RECORDER.get("errors", []))
            detail = f"{exc}" + (f" ({errors})" if errors else "")
        except Exception:
            detail = str(exc)
        state.update({"state": "error", "error": f"{detail}.{rescue}"})


@app.post("/api/recorder/start")
async def recorder_start(request: Request):
    ok, reason = _recorder_available()
    if not ok:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}
    with RECORDER_LOCK:
        if RECORDER.get("state") in {"recording", "stopping", "transcribing"}:
            return JSONResponse({"ok": False, "error": "A recording is already running."}, status_code=409)
        include_mic = bool(payload.get("include_mic", True))
        stop_event = threading.Event()
        loopback_chunks: list = []
        mic_chunks: list = []
        errors: list = []
        threads = [
            threading.Thread(
                target=_recorder_capture,
                args=("loopback", stop_event, loopback_chunks, errors),
                daemon=True,
            )
        ]
        if include_mic:
            threads.append(
                threading.Thread(
                    target=_recorder_capture,
                    args=("mic", stop_event, mic_chunks, errors),
                    daemon=True,
                )
            )
        RECORDER.clear()
        RECORDER.update({
            "state": "recording",
            "started_at": time.time(),
            "stop_event": stop_event,
            "threads": threads,
            "loopback": loopback_chunks,
            "mic": mic_chunks,
            "errors": errors,
            "include_mic": include_mic,
            "session": str(payload.get("session", "")),
            "session_label": str(payload.get("session_label", "")),
        })
        for thread in threads:
            thread.start()
    return JSONResponse({"ok": True})


def _recorder_request_stop() -> bool:
    """Stop capture once and save in the background, from the page or tray."""
    with RECORDER_LOCK:
        if RECORDER.get("state") != "recording":
            return False
        settings = _load_settings()
        model_name = settings.get("transcription_model", "base")
        RECORDER["state"] = "stopping"
        RECORDER["stop_event"].set()
        threading.Thread(
            target=_recorder_finalize,
            args=(
                RECORDER.get("include_mic", True),
                RECORDER.get("session", ""),
                RECORDER.get("session_label", ""),
                model_name,
            ),
            daemon=True,
        ).start()
    return True


@app.post("/api/recorder/stop")
async def recorder_stop():
    if not _recorder_request_stop():
        return JSONResponse({"ok": False, "error": "No recording is running."}, status_code=409)
    return JSONResponse({"ok": True})


def _recorder_status_payload() -> dict:
    # Starting a new recording clears RECORDER; use one coherent snapshot.
    with RECORDER_LOCK:
        recorder = dict(RECORDER)
    state = recorder.get("state", "idle")
    payload = {"state": state}
    if recorder.get("audio"):
        payload.update(audio=recorder["audio"], audio_url=recorder["audio_url"])
    if state == "recording":
        payload["elapsed"] = max(0, int(time.time() - recorder.get("started_at", time.time())))
        payload["warnings"] = list(recorder.get("errors", []))
    if state == "transcribing":
        payload["progress"] = recorder.get("progress", 0)
        payload["phase"] = recorder.get("phase", "")
    if state == "saved":
        payload["note"] = recorder.get("note", "")
        payload["url"] = recorder.get("url", "")
    if state == "error":
        payload["error"] = recorder.get("error", "")
    return payload


@app.get("/api/recorder/status")
def recorder_status():
    return JSONResponse(_recorder_status_payload())


@app.post("/api/spotter-live/append")
async def spotter_live_append(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the transcript chunk."}
    path = _safe_transcript_path(str(payload.get("file", "")))
    if path is None:
        return {"ok": False, "error": "Invalid transcript file name."}
    text = str(payload.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "Nothing to append."}
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        started = time.strftime("%Y-%m-%d %H:%M")
        path.write_text(f"# Spotter Live transcript\n\nStarted: {started}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n\n")
    return {"ok": True, "file": path.name}


def _spotter_live_clean_answer(answer: str) -> str:
    """Unwrap JSON/fenced answers so the spoken reply is clean prose.

    Some Spotter personas force JSON output ({"text": "..."}); strip that here.
    """
    text = (answer or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for key in ("text", "answer", "spoken_response", "response", "reply", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            parts = [v.strip() for v in data.values() if isinstance(v, str) and v.strip()]
            if parts:
                return " ".join(parts)
        # Malformed JSON (e.g. stray quotes): pull out the text value by regex.
        match = re.search(r'"text"?\s*:\s*"(.*?)"?\s*\}?\s*$', text, re.S)
        if match and match.group(1).strip():
            return match.group(1).strip()
    # An answer with no letters ({}, [], punctuation) is not speakable prose.
    if not re.search(r"[A-Za-z]", text):
        return ""
    return text


@app.post("/api/spotter-live/ask")
async def spotter_live_ask(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the question."}
    question = str(payload.get("question", "")).strip()
    if not question:
        return {"ok": False, "error": "Spotter Live needs a question."}

    transcript = ""
    path = _safe_transcript_path(str(payload.get("file", "")))
    if path is not None and path.exists():
        transcript = path.read_text(encoding="utf-8")
    # Screen the whole transcript before selecting bounded workshop evidence.
    review = note_quality.screen(transcript, str(payload.get("focus", "")))
    transcript_tail, _ = _select_body_excerpt(review["text"], 24000)

    settings = _load_settings()
    if not _llm_available(settings):
        extracted = note_quality.local_signals(review["text"], str(payload.get("focus", "")))
        query = question.lower()
        key = "actions" if "action" in query or "next step" in query else "pain_points" if "pain" in query or "problem" in query else "questions" if "question" in query else "observations"
        evidence = extracted[key]
        answer = " ".join(evidence[:4]) if evidence else "No matching workshop signals were found. Review the transcript for details."
        return {"ok": True, "answer": answer, "mode": "local", "message": "Local extraction; no AI interpretation."}

    name = settings.get("spotter_name", "Spotter")
    persona = settings.get("spotter_persona", "")

    def _live_prompt(include_persona: bool) -> str:
        persona_block = f"PERSONA (tone and expertise only — its output format rules do NOT apply):\n{persona}\n\n" if include_persona and persona else ""
        return (
            f"You are {name} Live, a real-time workshop copilot for a facilitator.\n"
            + persona_block
            + note_quality.WRITING_RULES + "\n" + note_quality.RELEVANCE_RULES + "\n"
            + "Below is the live transcript of the room captured so far. Treat it as your "
            "primary knowledge of what has happened in this workshop. Ground your answer "
            "in specifics from the transcript whenever they exist.\n\n"
            f"ROOM TRANSCRIPT (most recent last):\n{transcript_tail or '(no transcript captured yet)'}\n\n"
            f"FACILITATOR QUESTION:\n{question}\n\n"
            "IMPORTANT: Your entire reply must be plain spoken prose — the exact words "
            "you would say aloud. Never output JSON, braces, keys, code fences, or "
            "markdown headers, even if instructed elsewhere. 2-6 sentences."
        )

    answer = ""
    try:
        answer = _spotter_live_clean_answer(await asyncio.to_thread(_call_llm, _feature_settings(settings, "spotter"), _live_prompt(True)))
        if not answer and persona:
            # The persona's JSON formatting rules can win over the prose
            # instruction and yield {} — retry once without the persona.
            answer = _spotter_live_clean_answer(await asyncio.to_thread(_call_llm, _feature_settings(settings, "spotter"), _live_prompt(False)))
    except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
        return {"ok": False, "error": f"Spotter Live could not reach the model. {e}"}
    if not answer:
        return {"ok": False, "error": "The model returned an empty answer. Try asking again."}
    return {"ok": True, "answer": answer}


@app.websocket("/ws/spotter-live-stt")
async def spotter_live_stt(ws: WebSocket):
    """Proxy browser audio to ElevenLabs Scribe v2 Realtime and relay transcripts back."""
    await ws.accept()
    settings = _load_settings()
    el_key = settings.get("api_keys", {}).get("elevenlabs", "")
    if not el_key:
        await ws.send_text(json.dumps({"message_type": "error", "error": "No ElevenLabs key is saved in Settings."}))
        await ws.close()
        return
    try:
        import websockets
    except ImportError:
        await ws.send_text(json.dumps({"message_type": "error", "error": "The websockets package is missing. Run: pip install websockets"}))
        await ws.close()
        return

    url = (
        "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
        "?model_id=scribe_v2_realtime&audio_format=pcm_16000"
        "&commit_strategy=vad&vad_silence_threshold_secs=1.0"
        "&include_timestamps=true&timestamps_granularity=word"
    )
    headers = {"xi-api-key": el_key}
    try:
        connect = websockets.connect(url, additional_headers=headers, max_size=10 * 1024 * 1024)
    except TypeError:  # websockets < 14 uses extra_headers
        connect = websockets.connect(url, extra_headers=headers, max_size=10 * 1024 * 1024)

    try:
        async with connect as upstream:
            async def pump_up():
                while True:
                    msg = await ws.receive_text()
                    await upstream.send(msg)

            async def pump_down():
                async for msg in upstream:
                    await ws.send_text(msg if isinstance(msg, str) else msg.decode("utf-8"))

            tasks = [asyncio.create_task(pump_up()), asyncio.create_task(pump_down())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 — surface upstream failures to the client
        try:
            await ws.send_text(json.dumps({"message_type": "error", "error": f"Realtime transcription failed: {e}"}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/ws/spotter-live-openai-stt")
async def spotter_live_openai_stt(ws: WebSocket):
    """Keep the OpenAI key server-side while proxying live PCM transcription."""
    await ws.accept()
    settings = _load_settings()
    api_key = settings.get("api_keys", {}).get("openai", "")
    if not api_key:
        await ws.send_text(json.dumps({"type": "error", "error": {"message": "No OpenAI API key is saved in Settings."}}))
        await ws.close()
        return
    try:
        import websockets
    except ImportError:
        await ws.send_text(json.dumps({"type": "error", "error": {"message": "The websockets package is missing."}}))
        await ws.close()
        return

    model = settings.get("openai_realtime_transcription_model", "gpt-realtime-whisper")
    delay = settings.get("openai_realtime_transcription_delay", "low")
    # Transcription-only sessions use the Realtime transcription intent.
    # The speech-to-text model belongs in session.update, not in the socket URL.
    url = "wss://api.openai.com/v1/realtime?intent=transcription"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        connect = websockets.connect(url, additional_headers=headers, max_size=20 * 1024 * 1024)
    except TypeError:  # websockets < 14
        connect = websockets.connect(url, extra_headers=headers, max_size=20 * 1024 * 1024)

    try:
        async with connect as upstream:
            await upstream.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {"model": model, "language": "en", "delay": delay},
                            "turn_detection": None,
                        }
                    },
                },
            }))

            async def pump_up():
                while True:
                    raw = await ws.receive_text()
                    message = json.loads(raw)
                    if message.get("type") == "audio" and message.get("audio"):
                        await upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": message["audio"]}))
                    elif message.get("type") == "commit":
                        await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))

            async def pump_down():
                async for raw in upstream:
                    await ws.send_text(raw if isinstance(raw, str) else raw.decode("utf-8"))

            tasks = [asyncio.create_task(pump_up()), asyncio.create_task(pump_down())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_text(json.dumps({"type": "error", "error": {"message": f"OpenAI Realtime transcription failed: {e}"}}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str | None = Query(default=None),
    theme: str | None = Query(default=None),
):
    entries = load_all_entries()
    results = search_entries(entries, keyword=q, theme=theme)
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "search.html",
        {
            "q": q or "",
            "theme": theme or "",
            "results": results,
            **sidebar,
        },
    )


SKATER_LEVELS = [
    (0, "Grom", "Everyone starts somewhere. Push around and capture your first notes."),
    (20, "Pusher", "You're rolling — notes are landing and a session is taking shape."),
    (50, "Ollie", "First real air: consistent capture across sessions."),
    (100, "Kickflip", "Style points — typed signals, themes, and landed actions."),
    (175, "Boardslide", "Committed. Workshop memory is becoming a habit."),
    (275, "50-50 Grind", "Locked in. The GRIND is your home turf."),
    (400, "Vert Ripper", "Big lines across many workshops and follow-through to match."),
    (600, "900 Legend", "Rarefied air. Your vault is true organizational memory."),
]


def _skater_progress(entries) -> dict:
    """Gamified progress: XP from sessions, notes, and landed actions."""
    session_keys = {e.session_key for e in entries if e.session_key}
    note_count = len(entries)
    landed_count = sum(
        1 for e in entries if e.entry_type == "action" and e.lineup_status == "landed"
    )
    xp = note_count + len(session_keys) * 10 + landed_count * 5

    level_index = 0
    for i, (threshold, _name, _desc) in enumerate(SKATER_LEVELS):
        if xp >= threshold:
            level_index = i
    threshold, name, desc = SKATER_LEVELS[level_index]
    at_top = level_index == len(SKATER_LEVELS) - 1
    next_threshold, next_name = (None, None) if at_top else SKATER_LEVELS[level_index + 1][:2]
    if at_top:
        percent = 100
    else:
        span = max(next_threshold - threshold, 1)
        percent = min(99, int((xp - threshold) * 100 / span))
    return {
        "xp": xp,
        "level": level_index + 1,
        "level_count": len(SKATER_LEVELS),
        "name": name,
        "description": desc,
        "next_name": next_name,
        "next_threshold": next_threshold,
        "xp_to_next": None if at_top else next_threshold - xp,
        "percent": percent,
        "sessions": len(session_keys),
        "notes": note_count,
        "landed": landed_count,
    }


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    entries = load_all_entries()

    # Date histogram (entries per date)
    date_counts: dict[str, int] = {}
    for e in entries:
        if e.date:
            date_counts[e.date] = date_counts.get(e.date, 0) + 1
    timeline = sorted(date_counts.items())

    # Tag cloud (top 20)
    tag_counts: dict[str, int] = {}
    for e in entries:
        for t in e.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:20]

    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "stats.html",
        {
            "total": len(entries),
            "timeline": timeline,
            "top_tags": top_tags,
            "skater": _skater_progress(entries),
            **sidebar,
        },
    )


@app.get("/grind", response_class=HTMLResponse)
def grind(
    request: Request,
    session: str | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    run: str | None = Query(default=None),
):
    run_requested = str(run or "").strip().lower() in {"1", "true", "yes", "on"}
    all_entries = load_all_entries()
    all_session_rows = session_stats(all_entries)
    active_session_rows = [row for row in all_session_rows if str(row.get("status", "active")).lower() != "inactive"]
    active_session_keys = {row["key"] for row in active_session_rows}
    grind_entries = [
        entry
        for entry in all_entries
        if entry.status.strip().lower() != "inactive" and entry.session_key in active_session_keys
    ]
    session_allowed = not session or session in active_session_keys
    entries = filter_entries(
        grind_entries,
        session=session if session_allowed else "__inactive_session__",
        entry_type=entry_type,
        date_from=date_from,
        date_to=date_to,
    )
    data = graph_data(entries)
    grind_run = bool(run_requested and session and session_allowed)
    insights = _grind_insights(entries, data) if grind_run else design_insights(entries, data)
    if grind_run:
        try:
            save_grind_snapshot(session or "", insights, entries)
        except OSError:
            pass
    insights.setdefault("mode", "local")
    insights.setdefault("provider", "openai")
    general_settings = _load_settings()
    insights.setdefault("model", general_settings.get("model", "gpt-5.6"))
    insights.setdefault("reasoning_effort", general_settings.get("reasoning_effort", "medium"))
    insights.setdefault("error", "")
    export_params = {
        "session": session or "",
        "entry_type": entry_type or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
    }
    export_url = "/grind/export?" + urlencode({k: v for k, v in export_params.items() if v})
    sidebar = _sidebar_context()
    sidebar["sessions"] = active_session_rows
    selected_session_row = next(
        (row for row in active_session_rows if row["key"] == session),
        None,
    )
    if selected_session_row:
        scope_title = selected_session_row["label"]
        scope_description = (
            "This map contains only active notes from this session. Its rails show "
            "explicit evidence relationships and shared themes inside the session."
        )
    else:
        scope_title = "All active sessions"
        scope_description = (
            f"This combined map contains active notes from {len(active_session_rows)} active "
            "sessions. Rails can reveal explicit evidence relationships and shared themes "
            "within or across sessions."
        )
    import json
    return TEMPLATES.TemplateResponse(
        request,
        "graph.html",
        {
            "graph_json": json.dumps(data),
            "stats": data["stats"],
            "legend": data["legend"],
            "insights": insights,
            "filters": {
                "session": session or "",
                "entry_type": entry_type or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
            "grind_run": grind_run,
            "grind_requires_session": bool(run_requested and not session),
            "export_url": export_url,
            "scope_title": scope_title,
            "scope_description": scope_description,
            **sidebar,
        },
    )


@app.get("/grind/export")
def grind_export(
    session: str | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
):
    if not session:
        return RedirectResponse(url="/grind", status_code=303)

    all_entries = load_all_entries()
    active_session_keys = {
        row["key"]
        for row in session_stats(all_entries)
        if str(row.get("status", "active")).lower() != "inactive"
    }
    if session not in active_session_keys:
        return RedirectResponse(url="/grind", status_code=303)

    entries = filter_entries(
        [entry for entry in all_entries if entry.status.strip().lower() != "inactive"],
        session=session,
        entry_type=entry_type,
        date_from=date_from,
        date_to=date_to,
    )
    data = graph_data(entries)
    insights = _grind_insights(entries, data)
    try:
        save_grind_snapshot(session, insights, entries)
    except OSError:
        pass
    workbook = _make_xlsx(_grind_export_rows(insights))
    filename = f"SKATE-GRIND-{_slugify(session)}.xlsx"
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Backwards-compatible alias for the old URL
@app.get("/graph", response_class=HTMLResponse)
def graph_alias():
    return RedirectResponse(url="/grind", status_code=301)


@app.get("/theme-boards/{filename}")
def theme_board_image(filename: str):
    if filename not in {row[2] for row in ui_themes.PALETTES}:
        return Response(status_code=404)
    path = SKATE_ROOT / "theme-boards" / filename
    if not path.is_file():
        path = STATIC_DIR / "skateboards" / filename
    return FileResponse(path) if path.is_file() else Response(status_code=404)


@app.post("/api/theme-boards/open")
def open_theme_boards():
    folder = SKATE_ROOT / "theme-boards"
    folder.mkdir(parents=True, exist_ok=True)
    for row in ui_themes.PALETTES:
        target = folder / row[2]
        if not target.exists():
            shutil.copy2(STATIC_DIR / "skateboards" / row[2], target)
    palette_path = folder / "themes.json"
    if not palette_path.exists():
        palette_path.write_text(json.dumps({row[0]: dict(zip(ui_themes.COLORS, row[4])) for row in ui_themes.PALETTES}, indent=2), encoding="utf-8")
    if sys.platform == "win32":
        os.startfile(str(folder))
    return {"ok": True, "path": str(folder)}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str | None = Query(default=None)):
    settings = _load_settings()
    sidebar = _sidebar_context()
    return TEMPLATES.TemplateResponse(
        request,
        "settings.html",
        {
            "current_settings": _public_settings(settings),
            "model_options": MODEL_OPTIONS,
            "whisper_models": WHISPER_MODELS,
            "saved": saved == "1",
            **sidebar,
        },
    )


@app.post("/settings")
async def save_settings(request: Request):
    form = await _read_form(request)
    settings = _load_settings()

    model = form.get("model", "")
    valid_models = {item["id"] for item in OPENAI_MODEL_OPTIONS}
    if model not in valid_models:
        model = "gpt-5.6"

    provider = str(form.get("provider", settings.get("provider", "openai"))).strip()
    settings["provider"] = provider if provider in LLM_PROVIDERS else "openai"
    if form.get("ui_theme") in {row[0] for row in ui_themes.PALETTES}:
        settings["ui_theme"] = form["ui_theme"]
    if "recording_upload_limit_mb" in form:
        try:
            settings["recording_upload_limit_mb"] = max(250, min(4096, int(form["recording_upload_limit_mb"])))
        except (TypeError, ValueError):
            settings["recording_upload_limit_mb"] = 2048
    settings["model"] = model
    anthropic_model = str(form.get("anthropic_model", settings.get("anthropic_model", ""))).strip()
    valid_anthropic = {item["id"] for item in ANTHROPIC_MODEL_OPTIONS}
    settings["anthropic_model"] = anthropic_model if anthropic_model in valid_anthropic else "claude-sonnet-5"
    settings["openrouter_model"] = str(form.get("openrouter_model", settings.get("openrouter_model", ""))).strip() or DEFAULT_SETTINGS["openrouter_model"]
    settings["lmstudio_base_url"] = str(form.get("lmstudio_base_url", settings.get("lmstudio_base_url", ""))).strip() or DEFAULT_SETTINGS["lmstudio_base_url"]
    settings["lmstudio_model"] = str(form.get("lmstudio_model", settings.get("lmstudio_model", ""))).strip()
    spotter_model = str(form.get("spotter_model", settings.get("spotter_model", ""))).strip()
    settings["spotter_model"] = spotter_model if spotter_model in valid_models else ""
    spotter_anthropic = str(form.get("spotter_anthropic_model", settings.get("spotter_anthropic_model", ""))).strip()
    settings["spotter_anthropic_model"] = spotter_anthropic if spotter_anthropic in valid_anthropic else ""
    reasoning_efforts = {"none", "low", "medium", "high", "xhigh", "max"}
    for key, fallback in (
        ("reasoning_effort", "medium"),
        ("spotter_reasoning_effort", "low"),
    ):
        value = str(form.get(key, settings.get(key, fallback))).strip().lower()
        settings[key] = value if value in reasoning_efforts else fallback
    settings["openai_base_url"] = str(form.get("openai_base_url", settings.get("openai_base_url", ""))).strip() or "https://api.openai.com/v1"
    try:
        settings["max_tokens"] = max(128, min(16000, int(form.get("max_tokens", settings.get("max_tokens", 1920)))))
    except (TypeError, ValueError):
        settings["max_tokens"] = 1920
    transcription_model = form.get("transcription_model", settings.get("transcription_model", "base"))
    valid_whisper_models = {m["id"] for m in WHISPER_MODELS}
    settings["transcription_model"] = transcription_model if transcription_model in valid_whisper_models else "base"
    settings["spotter_name"] = str(form.get("spotter_name", settings.get("spotter_name", "Spotter"))).strip() or "Spotter"
    settings["spotter_subtitle"] = str(form.get("spotter_subtitle", settings.get("spotter_subtitle", ""))).strip()
    settings["spotter_persona"] = str(form.get("spotter_persona", settings.get("spotter_persona", ""))).strip() or DEFAULT_SETTINGS["spotter_persona"]
    settings["spotter_methodology"] = str(form.get("spotter_methodology", settings.get("spotter_methodology", ""))).strip() or DEFAULT_SETTINGS["spotter_methodology"]
    settings["spotter_style"] = str(form.get("spotter_style", settings.get("spotter_style", ""))).strip() or DEFAULT_SETTINGS["spotter_style"]
    settings["microphone"] = str(form.get("microphone", settings.get("microphone", "system-default"))).strip() or "system-default"
    settings["microphone_label"] = str(form.get("microphone_label", settings.get("microphone_label", ""))).strip()
    stt_provider = str(form.get("speech_to_text_provider", settings.get("speech_to_text_provider", "openai"))).strip()
    settings["speech_to_text_provider"] = stt_provider if stt_provider in {"local", "openai", "elevenlabs"} else "openai"
    tts_provider = str(form.get("text_to_speech_provider", settings.get("text_to_speech_provider", "local"))).strip()
    settings["text_to_speech_provider"] = tts_provider if tts_provider in {"local", "openai", "elevenlabs"} else "local"
    settings["speak_responses_aloud"] = _checked(form.get("speak_responses_aloud"))
    settings["openai_realtime_model"] = "gpt-realtime-mini"
    settings["openai_realtime_transcription_model"] = "gpt-realtime-whisper"
    realtime_delay = str(form.get("openai_realtime_transcription_delay", settings.get("openai_realtime_transcription_delay", "low"))).strip()
    settings["openai_realtime_transcription_delay"] = realtime_delay if realtime_delay in {"minimal", "low", "medium", "high", "xhigh"} else "low"
    realtime_voice = str(form.get("openai_realtime_voice", settings.get("openai_realtime_voice", "marin"))).strip()
    settings["openai_realtime_voice"] = realtime_voice if realtime_voice in {"marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"} else "marin"
    settings["openai_batch_transcription_model"] = "gpt-4o-mini-transcribe"
    settings["elevenlabs_voice_id"] = str(form.get("elevenlabs_voice_id", settings.get("elevenlabs_voice_id", ""))).strip() or DEFAULT_SETTINGS["elevenlabs_voice_id"]
    settings["elevenlabs_tts_model"] = str(form.get("elevenlabs_tts_model", settings.get("elevenlabs_tts_model", ""))).strip() or DEFAULT_SETTINGS["elevenlabs_tts_model"]
    settings["elevenlabs_stt_model"] = str(form.get("elevenlabs_stt_model", settings.get("elevenlabs_stt_model", ""))).strip() or DEFAULT_SETTINGS["elevenlabs_stt_model"]
    try:
        settings["streamdeck_port"] = max(1, min(65535, int(form.get("streamdeck_port", settings.get("streamdeck_port", 3030)))))
    except (TypeError, ValueError):
        settings["streamdeck_port"] = 3030
    settings["streamdeck_auto_send"] = _checked(form.get("streamdeck_auto_send"))
    for key_provider in ("openai", "anthropic", "openrouter", "elevenlabs"):
        settings.setdefault("api_keys", {}).setdefault(key_provider, "")

    for key_provider in ("openai", "anthropic", "openrouter", "elevenlabs"):
        if _checked(form.get(f"clear_{key_provider}_api_key")):
            settings["api_keys"][key_provider] = ""
            continue
        submitted = form.get(f"{key_provider}_api_key", "").strip()
        if submitted:
            settings["api_keys"][key_provider] = submitted

    _save_settings(settings)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


def _onenote_request_args(data: dict) -> dict:
    return {
        "source_path": str(data.get("source_path", "")).strip(),
        "mode": "single" if str(data.get("mode", "by_folder")) == "single" else "by_folder",
        "session_name": (str(data.get("session_name", "")).strip() or "OneNote Import"),
        "split_pages": bool(data.get("split_pages", True)),
    }


@app.post("/api/pick-folder")
def pick_folder():
    """Open a native folder picker on the local machine and return the chosen path."""
    import subprocess
    if os.name != "nt":
        return {"ok": False, "error": "The folder picker is Windows-only; type the path instead."}
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$f.Description = 'Select your OneNote export folder';"
        "$f.ShowNewFolderButton = $false;"
        "$top = New-Object System.Windows.Forms.Form;"
        "$top.TopMost = $true;"
        "if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($f.SelectedPath) }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True, text=True, timeout=180,
        )
        return {"ok": True, "path": (result.stdout or "").strip()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Could not open the folder picker. {e}"}


@app.post("/api/onenote-preview")
async def onenote_preview(request: Request):
    """Dry run: walk the export folder and report what would be imported."""
    data = await request.json()
    args = _onenote_request_args(data)
    if not args["source_path"]:
        return JSONResponse(
            {"ok": False, "error": "Enter the folder you copied your OneNote export into."},
            status_code=400,
        )
    try:
        plan = _onenote_build_plan(
            args["source_path"],
            mode=args["mode"],
            session_name=args["session_name"],
            split_pages=args["split_pages"],
            include_bodies=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse({"ok": False, "error": f"Preview failed: {exc}"}, status_code=500)
    return JSONResponse(plan)


@app.post("/api/onenote-import")
async def onenote_import_run(request: Request):
    """Convert and write the exported OneNote files into the vault."""
    data = await request.json()
    args = _onenote_request_args(data)
    if not args["source_path"]:
        return JSONResponse(
            {"ok": False, "error": "Enter the folder you copied your OneNote export into."},
            status_code=400,
        )
    try:
        plan = _onenote_build_plan(
            args["source_path"],
            mode=args["mode"],
            session_name=args["session_name"],
            split_pages=args["split_pages"],
            include_bodies=True,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse({"ok": False, "error": f"Import failed: {exc}"}, status_code=500)

    if not plan.get("ok") and not plan.get("notebooks"):
        return JSONResponse(plan, status_code=400)

    today = date.today().isoformat()
    written = 0
    written_notes: list[dict] = []
    sessions_touched: list[str] = []

    for nb in plan["notebooks"]:
        session_slug = _slugify(nb["name"])
        session_label = nb["name"]
        _ensure_session(session_slug, session_label)
        if session_slug not in sessions_touched:
            sessions_touched.append(session_slug)
        folder = _notes_folder()
        for note in nb["notes"]:
            title = (note.get("title") or "Untitled").strip() or "Untitled"
            body = note.get("body") or _default_note_body(title)
            base = f"{today}-{_slugify(title)}.md"
            path = folder / base
            counter = 2
            while path.exists():
                path = folder / f"{today}-{_slugify(title)}-{counter}.md"
                counter += 1
            _write_entry(
                path,
                title,
                today,
                "note",
                session_slug,
                session_label,
                "active",
                ["onenote-import", session_slug],
                [],
                [],
                "imported",
                "onenote import",
                body,
            )
            written += 1
            written_notes.append({
                "title": title,
                "session": session_slug,
                "file": path.relative_to(CONVERSATIONS).as_posix(),
            })

    plan["written"] = written
    plan["sessions_created"] = sessions_touched
    plan["written_notes"] = written_notes
    return JSONResponse(plan)


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    sidebar = _sidebar_context()
    sidebar["capture_marker_labels"] = CAPTURE_MARKER_LABELS
    return TEMPLATES.TemplateResponse(request, "about.html", sidebar)


@app.get("/about/recording", response_class=HTMLResponse)
def recording_guide(request: Request):
    return TEMPLATES.TemplateResponse(request, "recording_guide.html", _sidebar_context())


@app.get("/debug/vault", response_class=HTMLResponse)
def debug_vault():
    entries = load_all_entries()
    diagnostics = vault_diagnostics()
    lines = [
        "SKATE vault diagnostics",
        f"Loaded entries: {len(entries)}",
        f"SKATE_ROOT: {diagnostics['skate_root']}",
        f"CONVERSATIONS: {diagnostics['conversations']}",
        f"Conversations exists: {diagnostics['conversations_exists']}",
        f"Markdown files found: {diagnostics['markdown_count']}",
        "",
        "Sample files:",
        *diagnostics["sample_files"],
        "",
        "Load errors:",
        *(diagnostics["load_errors"] or ["None"]),
        "",
        "Candidate roots:",
    ]
    for candidate in diagnostics["candidate_roots"]:
        lines.append(
            f"{candidate['markdown_count']:>3} md | "
            f"{'yes' if candidate['has_conversations'] else ' no'} conversations | "
            f"{candidate['path']}"
        )
    body = "\n".join(lines)
    return HTMLResponse(f"<pre>{body}</pre>")


def _run_server(host: str, port: int, server_holder: dict):
    """Run uvicorn in a thread. Stores the Server instance so we can shut it down."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    server_holder["server"] = server
    server.run()


def _open_skate_window(
    url: str,
    *,
    hide_on_close: bool = False,
    window_holder: dict | None = None,
    quitting: threading.Event | None = None,
) -> bool:
    """Open SKATE in a small native window when pywebview is available."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NeraTech.SKATE.MemoryVault"
            )
            # Auto-accept the microphone permission prompt inside the WebView2
            # app window so Spotter's record-then-transcribe capture works
            # (SKATE only ever talks to 127.0.0.1, so this is safe locally).
            extra_args = "--use-fake-ui-for-media-stream"
            existing = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
            if extra_args not in existing:
                os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (existing + " " + extra_args).strip()
        import webview
        # WebView2 otherwise cancels attachment downloads without a prompt.
        webview.settings["ALLOW_DOWNLOADS"] = True
    except ImportError:
        return False

    try:
        icon_path = STATIC_DIR / "favicon.ico"
        window = webview.create_window(
            "SKATE",
            url,
            width=1280,
            height=860,
            min_size=(980, 680),
        )
        if window_holder is not None:
            window_holder["window"] = window
        if hide_on_close:
            def on_closing():
                if quitting is not None and quitting.is_set():
                    return True
                window.hide()
                return False

            window.events.closing += on_closing
        webview.start(icon=str(icon_path) if icon_path.exists() else None)
        return True
    except Exception as e:
        print(f"\n  WARNING: app window disabled ({e}).")
        return False


def _open_skate(url: str, app_window: bool):
    if app_window and _open_skate_window(url):
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _tray_record_image():
    """Draw a crisp record button that remains visible on either tray color."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((28, 28, 228, 228), fill="#d64545", outline="#f8fafc", width=8)
    return image.resize((64, 64), Image.Resampling.LANCZOS)


def _tray_idle_image():
    """Reuse the application's skateboard artwork for the idle tray icon."""
    from PIL import Image

    with Image.open(STATIC_DIR / "favicon.ico") as image:
        return image.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)


def _tray_recorder_tooltip(status: dict | None = None) -> str:
    status = _recorder_status_payload() if status is None else status
    state = status["state"]
    if state == "recording":
        elapsed = status["elapsed"]
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        warning = " — Check audio in SKATE" if status.get("warnings") else ""
        return f"SKATE — Recording {hours:02}:{minutes:02}:{seconds:02}{warning}"
    detail = {
        "stopping": "Preparing transcript",
        "transcribing": f"Transcribing {max(0, min(100, int(status.get('progress', 0))))}%",
        "saved": "Audio & transcript saved",
        "error": "Recording failed; open SKATE",
    }.get(state)
    return "SKATE — Not recording" + (f" — {detail}" if detail else "")


def _tray_can_stop_recording(item=None) -> bool:
    with RECORDER_LOCK:
        return RECORDER.get("state") == "recording"


def _tray_stop_recording(icon, item):
    _recorder_request_stop()


def _sync_tray_recording(icon, idle_image, record_image):
    """Refresh status without recreating the native icon on every clock tick."""
    status = _recorder_status_payload()
    image = record_image if status["state"] == "recording" else idle_image
    if icon.icon is not image:
        icon.icon = image
        icon.update_menu()
    title = _tray_recorder_tooltip(status)
    if icon.title != title:
        icon.title = title


def _launch_with_tray(host: str, port: int, open_browser: bool, app_window: bool):
    """Launch SKATE with a system tray icon. Server runs in background thread."""
    try:
        import pystray
        idle_image = _tray_idle_image()
        record_image = _tray_record_image()
    except ImportError as e:
        print(f"\n  WARNING: tray icon disabled ({e}).")
        print("  Install with: pip install pystray pillow")
        print("  Falling back to terminal-only mode.\n")
        _run_no_tray(host, port, open_browser, app_window)
        return

    url = f"http://{host}:{port}"

    server_holder: dict = {}
    server_thread = threading.Thread(
        target=_run_server, args=(host, port, server_holder), daemon=True
    )
    server_thread.start()

    window_holder: dict = {}
    quitting = threading.Event()

    def show_window():
        APP_SHOW_REQUESTED.clear()
        window = window_holder.get("window")
        if window is not None:
            try:
                window.show()
                try:
                    window.restore()
                except Exception:
                    pass
                return
            except Exception:
                pass
        _open_skate(url, False)

    def on_open(icon, item):
        show_window()

    def watch_show_requests():
        while not quitting.is_set():
            if APP_SHOW_REQUESTED.wait(timeout=0.5):
                if quitting.is_set():
                    return
                show_window()

    threading.Thread(target=watch_show_requests, daemon=True).start()

    def on_quit(icon, item):
        quitting.set()
        APP_SHOW_REQUESTED.set()
        srv = server_holder.get("server")
        if srv is not None:
            srv.should_exit = True
        window = window_holder.get("window")
        if window is not None:
            window.destroy()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open SKATE", on_open, default=True),
        pystray.MenuItem(
            "Stop recording & save", _tray_stop_recording,
            enabled=_tray_can_stop_recording,
        ),
        pystray.MenuItem(f"Running at {url}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit SKATE", on_quit),
    )

    icon = pystray.Icon(
        "SKATE",
        record_image if _tray_can_stop_recording() else idle_image,
        _tray_recorder_tooltip(),
        menu,
    )

    def watch_recording_status():
        while not quitting.wait(0.5):
            if icon.visible:
                _sync_tray_recording(icon, idle_image, record_image)

    threading.Thread(target=watch_recording_status, daemon=True).start()

    print(f"\n  SKATE running at {url}")
    print(f"  Vault: {HERE.parent}")
    print("  The tray shows a skateboard when idle and a red circle while recording.\n")

    # Wait briefly so the server is ready before opening the UI.
    time.sleep(1.0)
    if open_browser and app_window:
        # The tray runs alongside pywebview. Closing the native window hides
        # it; only the tray's Exit SKATE command terminates the application.
        icon.run_detached()
        if _open_skate_window(
            url,
            hide_on_close=True,
            window_holder=window_holder,
            quitting=quitting,
        ):
            quitting.set()
            icon.stop()
            srv = server_holder.get("server")
            if srv is not None:
                srv.should_exit = True
            server_thread.join(timeout=3.0)
            return
        icon.stop()
    elif open_browser:
        _open_skate(url, app_window)

    icon.run()  # Blocks the main thread. Returns when Exit SKATE is clicked.

    # After tray exits, give the server a moment to clean up
    quitting.set()
    srv = server_holder.get("server")
    if srv is not None:
        srv.should_exit = True
    server_thread.join(timeout=3.0)


def _run_no_tray(host: str, port: int, open_browser: bool, app_window: bool):
    """Run server in foreground with no tray icon."""
    import uvicorn

    url = f"http://{host}:{port}"
    print(f"\n  SKATE running at {url}")
    print(f"  Vault: {HERE.parent}")
    print(f"  Press Ctrl+C to stop.\n")

    if open_browser and app_window:
        server_holder: dict = {}
        server_thread = threading.Thread(
            target=_run_server, args=(host, port, server_holder), daemon=True
        )
        server_thread.start()
        time.sleep(1.0)
        if not _open_skate_window(url):
            webbrowser.open(url)
            server_thread.join()
            return
        srv = server_holder.get("server")
        if srv is not None:
            srv.should_exit = True
        server_thread.join(timeout=3.0)
        return

    if open_browser:
        # Delay browser open until server is bound
        def _open_later():
            time.sleep(1.0)
            _open_skate(url, app_window)
        threading.Thread(target=_open_later, daemon=True).start()

    uvicorn.run(app, host=host, port=port)


def _acquire_single_instance() -> bool:
    """Allow only one SKATE desktop process in the current Windows session."""
    global _SINGLE_INSTANCE_MUTEX
    if not sys.platform.startswith("win"):
        return True
    import ctypes

    mutex = ctypes.windll.kernel32.CreateMutexW(
        None,
        False,
        "Local\\NeraTech.SKATE.SingleInstance",
    )
    if not mutex:
        return True
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(mutex)
        return False
    _SINGLE_INSTANCE_MUTEX = mutex  # Keep the handle alive for this process.
    return True


def _show_existing_instance(host: str, port: int) -> None:
    """Signal the first SKATE process to restore its native window."""
    try:
        request = UrlRequest(
            f"http://{host}:{port}/api/app/show",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2):
            pass
    except Exception:
        # The first process may still be starting. It will open normally.
        pass


def main():
    parser = argparse.ArgumentParser(description="Run the SKATE UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Run in foreground with no system tray icon",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open the browser on launch",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open in the default browser instead of a SKATE app window",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on file changes (dev mode, disables tray)",
    )
    args = parser.parse_args()

    open_browser = not args.no_browser
    app_window = not args.browser

    if not args.reload and not _acquire_single_instance():
        _show_existing_instance(args.host, args.port)
        return

    if args.reload:
        # Reload mode does not play well with threaded tray, so fall back.
        import uvicorn

        url = f"http://{args.host}:{args.port}"
        print(f"\n  SKATE running at {url} (reload mode)\n")
        uvicorn.run("app:app", host=args.host, port=args.port, reload=True)
        return

    if args.no_tray:
        _run_no_tray(args.host, args.port, open_browser, app_window)
    else:
        _launch_with_tray(args.host, args.port, open_browser, app_window)


if __name__ == "__main__":
    main()
