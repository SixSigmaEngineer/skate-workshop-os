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
from urllib.parse import parse_qs, unquote, urlencode
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError
from xml.sax.saxutils import escape as xml_escape

import frontmatter
import markdown

import embeddings
import asyncio

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from skate_lib import (
    CONVERSATIONS,
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
MAX_LOCAL_AUDIO_BYTES = 250 * 1024 * 1024
TRANSCRIPTION_JOBS: dict[str, dict] = {}
TRANSCRIPTION_JOBS_LOCK = threading.Lock()
WHISPER_PROGRESS_LOCK = threading.Lock()
WHISPER_MODEL_LOCK = threading.Lock()
WHISPER_MODEL_CACHE: dict[str, object] = {"name": None, "model": None}
APP_SHOW_REQUESTED = threading.Event()
_SINGLE_INSTANCE_MUTEX = None

OPENAI_MODEL_OPTIONS = [
    {"id": "gpt-5.6", "label": "GPT-5.6 Sol — frontier"},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra — balanced"},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna — efficient"},
]
MODEL_OPTIONS = {"openai": OPENAI_MODEL_OPTIONS}

DEFAULT_SETTINGS = {
    "provider": "openai",
    "model": "gpt-5.6",
    "spotter_model": "",
    "spotter_reasoning_effort": "low",
    "reasoning_effort": "medium",
    "api_keys": {"openai": "", "elevenlabs": ""},
    "transcription_model": "base",
    "openai_base_url": "https://api.openai.com/v1",
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


def _decorate_capture_markers(body_html: str) -> str:
    """Apply the capture-button color language to rendered note bullets."""
    def replace_marker(match: re.Match) -> str:
        code = match.group(1).upper()
        label = CAPTURE_MARKER_LABELS[code]
        return (
            f'<li class="capture-line capture-line-{code.lower()}">'
            f'<span class="capture-marker capture-marker-{code.lower()}" title="{label}">#{code}:</span> '
        )

    return re.sub(r"<li>\s*#([POAQRSI]):\s*", replace_marker, body_html, flags=re.I)

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
        "lmstudio_base_url",
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
    settings["provider"] = "openai"
    valid_models = {m["id"] for m in OPENAI_MODEL_OPTIONS}
    if settings.get("model") not in valid_models:
        settings["model"] = "gpt-5.6"
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
    return settings


def _save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _public_settings(settings: dict) -> dict:
    public = dict(settings)
    public["api_key_present"] = {
        provider: bool(settings.get("api_keys", {}).get(provider))
        for provider in ("openai", "elevenlabs")
    }
    public.pop("api_keys", None)
    return public


def _llm_available(settings: dict) -> bool:
    return bool(settings.get("api_keys", {}).get("openai"))


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
    return {
        "sessions": session_stats(entries),
        "themes": theme_stats(entries),
        "entry_types": ENTRY_TYPES,
        "consulting_themes": CONSULTING_THEMES,
        "relationship_types": RELATIONSHIP_TYPES,
        "spotter_modes": SPOTTER_MODES,
        "total_entries": len(entries),
        "logo_exists": (STATIC_DIR / "logo.png").exists(),
        "vault_path": str(SKATE_ROOT),
        "settings": _public_settings(_load_settings()),
    }


def _entry_payload(entries) -> list[dict]:
    payload = []
    for entry in entries[:40]:
        payload.append(
            {
                "title": entry.title,
                "date": entry.date,
                "type": entry.entry_type,
                "themes": entry.themes,
                "tags": entry.tags,
                "summary": entry.summary[:900],
                "capture_markers": capture_markers(entry),
            }
        )
    return payload


def _synthesis_prompt(entries, graph: dict) -> str:
    payload = {
        "entries": _entry_payload(entries),
        "graph_stats": graph.get("stats", {}),
    }
    return (
        "You are helping synthesize a design-thinking workshop in SKATE. "
        "Treat explicit capture markers as the primary workshop evidence: "
        "#P pains and unmet needs; #O direct observations; #Q open questions and HMW seeds; "
        "#A owned actions or experiments; #S proposed solutions; #R recommendations; "
        "and #I synthesized insights. Do not flatten these categories or invent evidence. "
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
        raise ValueError(f"API returned HTTP {e.code}: {detail or e.reason}") from e


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


def _elevenlabs_transcribe(audio_bytes: bytes, filename: str, content_type: str, api_key: str, model_id: str = "scribe_v1") -> str:
    """Transcribe audio with the ElevenLabs Scribe speech-to-text API."""
    response = _post_multipart(
        "https://api.elevenlabs.io/v1/speech-to-text",
        {"xi-api-key": api_key},
        {"model_id": model_id or "scribe_v1"},
        {"file": {
            "filename": filename or "recording.webm",
            "content_type": content_type or "audio/webm",
            "content": audio_bytes,
        }},
        timeout=120,
    )
    return str(response.get("text", "")).strip()


def _openai_transcribe(audio_bytes: bytes, filename: str, content_type: str, api_key: str, model_id: str) -> str:
    """Transcribe a bounded recording with OpenAI's Audio API."""
    response = _post_multipart(
        "https://api.openai.com/v1/audio/transcriptions",
        {"Authorization": f"Bearer {api_key}"},
        {"model": model_id or "gpt-4o-mini-transcribe"},
        {"file": {
            "filename": filename or "recording.webm",
            "content_type": content_type or "audio/webm",
            "content": audio_bytes,
        }},
        timeout=120,
    )
    return str(response.get("text", "")).strip()


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
    """Return OpenAI settings with a feature-specific GPT-5.6 model and effort."""
    model = str(settings.get(f"{feature}_model") or "").strip()
    reasoning_effort = str(settings.get(f"{feature}_reasoning_effort") or "").strip()
    if not model and not reasoning_effort:
        return settings
    eff = dict(settings)
    eff["provider"] = "openai"
    if model:
        eff["model"] = model
    if reasoning_effort:
        eff["reasoning_effort"] = reasoning_effort
    return eff


def _grind_settings(settings: dict) -> dict:
    """Use the configured General GPT-5.6 model and reasoning for GRIND."""
    eff = dict(settings)
    eff["provider"] = "openai"
    return eff


def _call_llm(settings: dict, prompt: str, model: str | None = None) -> str:
    provider = settings.get("provider", "openai")
    model = model or settings["model"]
    api_key = settings.get("api_keys", {}).get(provider, "")
    max_tokens = int(settings.get("max_tokens", 1920))
    if provider != "openai":
        raise ValueError("SKATE currently supports OpenAI GPT-5.6 only.")
    if not api_key:
        raise ValueError("Missing OpenAI API key.")

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
        except HTTPError:
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

    raise ValueError("SKATE currently supports OpenAI GPT-5.6 only.")


def _grind_insights(entries, graph: dict) -> dict:
    settings = _load_settings()
    grind_settings = _grind_settings(settings)
    local = design_insights(entries, graph)
    local["mode"] = "local"
    local["provider"] = "openai"
    local["model"] = grind_settings.get("model", "gpt-5.6")
    local["reasoning_effort"] = grind_settings.get("reasoning_effort", "medium")
    local["error"] = ""

    if not _llm_available(grind_settings):
        local["error"] = "No OpenAI API key is saved; showing local synthesis."
        return local

    try:
        text = _call_llm(grind_settings, _synthesis_prompt(entries, graph))
        ai = _normalize_ai_insights(_extract_json_object(text), entries)
        ai["mode"] = "ai"
        ai["provider"] = "openai"
        ai["model"] = grind_settings.get("model", "gpt-5.6")
        ai["reasoning_effort"] = grind_settings.get("reasoning_effort", "medium")
        ai["error"] = ""
        ai["marker_counts"] = local.get("marker_counts", {})
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
    return f"""Compress this SKATE markdown note into a consulting memory block.

This is not a transcript summary. Preserve high-signal observations, evidence, themes, decisions, risks, and next actions. The output should help a consultant retrieve the note later and understand why it matters in a workshop or transformation engagement.

Return only JSON with:
{{
  "gist": "one sentence",
  "consulting_context": "the main consulting context for this note",
  "key_points": ["3 to 6 bullets"],
  "pain_points": ["0 to 5 bullets"],
  "actions": ["0 to 5 bullets"],
  "questions": ["0 to 5 bullets"],
  "agent_memory": "compact paragraph under 120 words written as reusable long-term memory"
}}

Title: {title}
Tags: {tags}

Markdown note:
{body[:8000]}
"""


def _local_note_compression(title: str, tags: str, body: str) -> dict:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    plain_lines = [
        re.sub(r"^#+\s*", "", line)
        for line in lines
        if not line.startswith("---") and not line.startswith("```")
    ]
    markers = {
        "pain_points": [],
        "actions": [],
        "questions": [],
    }
    for line in plain_lines:
        match = re.match(r"^#([PAQ]):\s*(.+)$", line, flags=re.I)
        if not match:
            continue
        code, text = match.group(1).upper(), match.group(2).strip()
        if code == "P":
            markers["pain_points"].append(text)
        elif code == "A":
            markers["actions"].append(text)
        elif code == "Q":
            markers["questions"].append(text)

    gist_source = next((line for line in plain_lines if line and not line.startswith("#")), title)
    key_points = []
    for line in plain_lines:
        cleaned = re.sub(r"^[-*> ]+", "", line).strip()
        if cleaned and cleaned not in key_points and not cleaned.lower().startswith(("summary", "notes")):
            key_points.append(cleaned)
        if len(key_points) >= 5:
            break

    agent_memory = _plain_text_excerpt(" ".join(key_points or [gist_source]), 520)
    return {
        "gist": _plain_text_excerpt(gist_source or title, 180),
        "consulting_context": f"Tags {tags or 'none'} provide retrieval rails for this note.",
        "key_points": key_points[:6],
        "pain_points": markers["pain_points"][:5],
        "actions": markers["actions"][:5],
        "questions": markers["questions"][:5],
        "agent_memory": agent_memory,
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
    def list_of_strings(key: str, limit: int) -> list[str]:
        values = raw.get(key, [])
        if not isinstance(values, list):
            return fallback.get(key, [])
        out = []
        for item in values:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
        return out[:limit]

    return {
        "gist": str(raw.get("gist", "")).strip() or fallback["gist"],
        "consulting_context": str(raw.get("consulting_context", "")).strip() or fallback["consulting_context"],
        "key_points": list_of_strings("key_points", 6),
        "pain_points": list_of_strings("pain_points", 5),
        "actions": list_of_strings("actions", 5),
        "questions": list_of_strings("questions", 5),
        "agent_memory": str(raw.get("agent_memory", "")).strip() or fallback["agent_memory"],
        "mode": "ai",
    }


def _compression_markdown(compression: dict) -> str:
    def bullets(items: list[str]) -> str:
        if not items:
            return "- None captured"
        return "\n".join(f"- {item}" for item in items)

    return f"""## Consultant Memory Compression

**Gist:** {compression["gist"]}

**Consulting context:** {compression["consulting_context"]}

**Compression purpose:** Reusable consultant memory organized around themes, evidence, and next-action value.

**Key points**
{bullets(compression["key_points"])}

**Pain points**
{bullets(compression["pain_points"])}

**Actions**
{bullets(compression["actions"])}

**Questions**
{bullets(compression["questions"])}

**Agent memory**
{compression["agent_memory"]}
"""


def _transcript_summary_prompt(title: str, transcript: str) -> str:
    return f"""Turn this raw workshop or meeting transcript into clean, concise SKATE meeting notes.

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
  "tags": ["3 to 7 lowercase tags"]
}}

Title: {title}

Transcript:
{transcript[:40000]}
"""


def _local_transcript_summary(title: str, transcript: str) -> dict:
    sentences = re.split(r"(?<=[.!?])\s+", transcript.strip())
    clean = [s.strip() for s in sentences if s.strip()]
    pain_words = ("pain", "problem", "friction", "delay", "risk", "manual", "hard", "stuck", "missing", "slow")
    action_words = ("need to", "should", "follow up", "next step", "action item", "todo", "assign", "build", "create")
    solution_words = ("solution", "we could", "prototype", "experiment", "pilot", "idea is")
    recommendation_words = ("recommend", "recommendation", "we propose", "proposed approach")
    insight_words = ("because", "means", "pattern", "root cause", "suggests")

    def contains_phrase(sentence: str, phrases: tuple[str, ...]) -> bool:
        lowered = sentence.lower()
        return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered) for phrase in phrases)

    buckets = {
        "pain_points": [],
        "actions": [],
        "questions": [],
        "solutions": [],
        "recommendations": [],
        "insights": [],
        "observations": [],
    }
    for sentence in clean:
        if "?" in sentence:
            bucket = "questions"
        elif contains_phrase(sentence, recommendation_words):
            bucket = "recommendations"
        elif contains_phrase(sentence, solution_words):
            bucket = "solutions"
        elif contains_phrase(sentence, action_words):
            bucket = "actions"
        elif contains_phrase(sentence, pain_words):
            bucket = "pain_points"
        elif contains_phrase(sentence, insight_words):
            bucket = "insights"
        else:
            bucket = "observations"
        if len(buckets[bucket]) < 5:
            buckets[bucket].append(sentence)

    if not buckets["observations"]:
        buckets["observations"] = clean[:3]

    return {
        "summary": _plain_text_excerpt(" ".join(clean[:4]) or transcript or title, 650),
        "observations": buckets["observations"],
        "pain_points": buckets["pain_points"],
        "actions": buckets["actions"],
        "questions": buckets["questions"],
        "solutions": buckets["solutions"],
        "recommendations": buckets["recommendations"],
        "insights": buckets["insights"],
        "tags": [],
        "mode": "local",
    }


def _normalize_transcript_summary(raw: dict, fallback: dict) -> dict:
    def strings(key: str, limit: int) -> list[str]:
        values = raw.get(key, [])
        if not isinstance(values, list):
            return fallback.get(key, [])
        out = []
        for item in values:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
        return out[:limit]

    tags = []
    for tag in raw.get("tags", []):
        tag = re.sub(r"[^a-z0-9-]+", "-", str(tag).strip().lower()).strip("-")
        if tag and tag not in tags:
            tags.append(tag)

    return {
        "summary": str(raw.get("summary", "")).strip() or fallback["summary"],
        "observations": strings("observations", 7),
        "pain_points": strings("pain_points", 5),
        "actions": strings("actions", 7),
        "questions": strings("questions", 5),
        "solutions": strings("solutions", 5),
        "recommendations": strings("recommendations", 5),
        "insights": strings("insights", 5),
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
    signal_text = "\n".join(signals) if signals else "- No structured signals were captured."

    return f"""## AI-Cleaned Meeting Notes

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
{text[:12000]}
"""


def _local_spotter_response(mode: dict, text: str) -> dict:
    summary = _plain_text_excerpt(text, 500)
    return {
        "spoken_response": f"Captured as {mode['label']}. I would validate the impact, owner, and next decision before moving on.",
        "title": f"{mode['label']}: {_plain_text_excerpt(text, 70) or 'Workshop Capture'}",
        "entry_type": mode["entry_type"],
        "themes": [
            theme
            for theme in CONSULTING_THEMES
            if any(word in text.lower() for word in theme.lower().split())
        ][:5],
        "summary": summary,
        "evidence": [summary] if summary else [],
        "insights": [],
        "recommendations": [],
        "actions": [],
        "questions": ["What evidence would confirm this?", "Who owns the next step?"],
        "relationships": [],
        "mode": "local",
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


def _local_whisper_transcribe(audio_bytes: bytes, filename: str, content_type: str, model_name: str, progress_callback=None) -> str:
    def report(percent: int, phase: str) -> None:
        if progress_callback:
            progress_callback(max(0, min(99, int(percent))), phase)

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
    post = frontmatter.Post(body.strip() + "\n", **metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _default_note_body(title: str, summary: str = "") -> str:
    first_observation = summary.strip()
    observation_line = f"- #O: {first_observation}" if first_observation else "- #O: "
    return f"""# {title}

## Meeting notes

{observation_line}
- #P:
- #Q:
- #A:

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
    for match in re.finditer(r"(?m)^\s*[-*]\s+#A:\s*(.+?)\s*$", entry.body or ""):
        text = match.group(1).strip()
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
    entry.path.write_text(frontmatter.dumps(post), encoding="utf-8")
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
            "body": body or _default_note_body(note_title or "Untitled", note_summary),
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
    path.write_text(frontmatter.dumps(frontmatter.Post(body, **metadata)), encoding="utf-8")
    return RedirectResponse(url=f"/session/{session}", status_code=303)


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
    path.write_text(frontmatter.dumps(frontmatter.Post(body, **metadata)), encoding="utf-8")


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
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    if str(form.get("return_to", "")).strip() == "sessions":
        return RedirectResponse(url="/sessions", status_code=303)
    return RedirectResponse(url=f"/session/{session}", status_code=303)


@app.get("/entry/{file_id:path}", response_class=HTMLResponse)
def view_entry(request: Request, file_id: str):
    entry = find_entry_by_id(file_id)
    if entry is None:
        return HTMLResponse("Entry not found", status_code=404)
    MD.reset()
    # Python Markdown treats ``#P:`` after a list marker as an ATX heading.
    # Escape SKATE's capture markers only for rendering; the markdown source
    # remains portable and human-readable as ``- #P: ...``.
    render_body = re.sub(r"(?m)^(\s*-\s+)#([POAQRSI]):", r"\1\\#\2:", entry.body)
    body_html = _decorate_capture_markers(MD.convert(render_body))
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
            "message": "No OpenAI API key is saved, so SKATE used a local suggestion.",
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


@app.post("/api/compress-note")
async def compress_note(request: Request):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the note text."}

    title = str(payload.get("title", "")).strip() or "Untitled"
    tags = str(payload.get("tags", "")).strip()
    body = str(payload.get("body", "")).strip()
    fallback = _local_note_compression(title, tags, body)
    settings = _load_settings()

    if not _llm_available(settings):
        markdown_block = _compression_markdown(fallback)
        return {
            "ok": True,
            "compression": fallback,
            "markdown": markdown_block,
            "message": "No OpenAI API key is saved, so SKATE used local compression.",
        }

    try:
        response_text = _call_llm(settings, _compression_prompt(title, tags, body))
        raw = _extract_json_object(response_text)
        compression = _normalize_compression(raw, fallback)
        compression["provider"] = settings["provider"]
        compression["model"] = settings["model"]
        return {"ok": True, "compression": compression, "markdown": _compression_markdown(compression)}
    except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
        fallback["error"] = str(e)
        return {
            "ok": True,
            "compression": fallback,
            "markdown": _compression_markdown(fallback),
            "message": f"AI compression failed, so SKATE used local compression. {e}",
        }


def _perform_transcription(audio_bytes: bytes, filename: str, content_type: str, requested_model: str, progress_callback=None) -> dict:
    def report(percent: int, phase: str) -> None:
        if progress_callback:
            progress_callback(percent, phase)

    settings = _load_settings()
    valid_whisper_models = {m["id"] for m in WHISPER_MODELS}
    model_name = requested_model if requested_model in valid_whisper_models else settings.get("transcription_model", "base")
    stt_provider = str(settings.get("speech_to_text_provider", "local") or "local").strip().lower()
    el_key = settings.get("api_keys", {}).get("elevenlabs", "")
    openai_key = settings.get("api_keys", {}).get("openai", "")

    if stt_provider == "elevenlabs":
        if not el_key:
            return {"ok": False, "error": "ElevenLabs Speech-to-Text is selected, but no ElevenLabs API key is saved. Choose Local in Settings or add a key."}
        stt_model = settings.get("elevenlabs_stt_model", "scribe_v2")
        try:
            report(15, "Sending recording to ElevenLabs")
            transcript = _elevenlabs_transcribe(audio_bytes, filename, content_type, el_key, stt_model)
            report(98, "Finalizing transcript")
            if transcript:
                return {"ok": True, "transcript": transcript, "model": stt_model, "mode": "elevenlabs-scribe"}
            return {"ok": False, "error": "ElevenLabs returned an empty transcript. Confirm your ElevenLabs key has Speech-to-Text (Scribe) access."}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as e:
            return {"ok": False, "error": f"ElevenLabs transcription failed: {e}"}

    if stt_provider == "openai":
        if not openai_key:
            return {"ok": False, "error": "OpenAI Speech-to-Text is selected, but no OpenAI API key is saved."}
        stt_model = settings.get("openai_batch_transcription_model", "gpt-4o-mini-transcribe")
        try:
            report(15, "Sending recording to OpenAI")
            transcript = _openai_transcribe(audio_bytes, filename, content_type, openai_key, stt_model)
            report(98, "Finalizing transcript")
            if transcript:
                return {"ok": True, "transcript": transcript, "model": stt_model, "mode": "openai-transcribe"}
            return {"ok": False, "error": "OpenAI returned an empty transcript."}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as e:
            return {"ok": False, "error": f"OpenAI transcription failed: {e}"}

    try:
        transcript = _local_whisper_transcribe(audio_bytes, filename, content_type, model_name, progress_callback=progress_callback)
        if not transcript:
            return {"ok": False, "error": "Local Whisper returned an empty transcript."}
        return {"ok": True, "transcript": transcript, "model": model_name, "mode": "local-whisper"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Local transcription failed. {e}"}


@app.post("/api/transcribe-audio")
async def transcribe_audio(request: Request):
    upload_type = str(request.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    if upload_type == "application/octet-stream":
        filename = unquote(str(request.headers.get("x-skate-filename", "recording.webm"))).strip() or "recording.webm"
        content_type = str(request.headers.get("x-skate-content-type", "")).strip() or mimetypes.guess_type(filename)[0] or "audio/webm"
        requested_model = str(request.headers.get("x-skate-model", "")).strip()
        audio_bytes = await request.body()
    else:
        # Backwards compatibility for Spotter and previously opened note tabs.
        try:
            payload = json.loads((await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "error": "Could not read the recording upload."}

        filename = str(payload.get("filename", "recording.webm")).strip() or "recording.webm"
        content_type = str(payload.get("content_type", "")).strip() or mimetypes.guess_type(filename)[0] or "audio/webm"
        requested_model = str(payload.get("model", "")).strip()
        data_url = str(payload.get("data", ""))
        if "," in data_url:
            data_url = data_url.split(",", 1)[1]
        try:
            audio_bytes = base64.b64decode(data_url, validate=True)
        except (ValueError, base64.binascii.Error):
            return {"ok": False, "error": "The recording file could not be decoded."}
    if not audio_bytes:
        return {"ok": False, "error": "The recording file was empty."}
    if len(audio_bytes) > MAX_LOCAL_AUDIO_BYTES:
        return {"ok": False, "error": "Audio and video recordings must be 250 MB or smaller for local SKATE transcription."}

    return _perform_transcription(audio_bytes, filename, content_type, requested_model)


def _update_transcription_job(job_id: str, **changes) -> None:
    with TRANSCRIPTION_JOBS_LOCK:
        job = TRANSCRIPTION_JOBS.get(job_id)
        if not job:
            return
        if "progress" in changes:
            changes["progress"] = max(int(job.get("progress", 0)), min(100, int(changes["progress"])))
        job.update(changes)
        job["updated_at"] = time.time()


def _run_transcription_job(job_id: str, audio_bytes: bytes, filename: str, content_type: str, requested_model: str) -> None:
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


@app.post("/api/transcription-jobs")
async def start_transcription_job(request: Request):
    audio_bytes = await request.body()
    filename = unquote(str(request.headers.get("x-skate-filename", "recording.webm"))).strip() or "recording.webm"
    content_type = str(request.headers.get("x-skate-content-type", "")).strip() or mimetypes.guess_type(filename)[0] or "audio/webm"
    requested_model = str(request.headers.get("x-skate-model", "")).strip()
    if not audio_bytes:
        return JSONResponse({"ok": False, "error": "The recording file was empty."}, status_code=400)
    if len(audio_bytes) > MAX_LOCAL_AUDIO_BYTES:
        return JSONResponse({"ok": False, "error": "Audio and video recordings must be 250 MB or smaller for local SKATE transcription."}, status_code=413)

    now = time.time()
    with TRANSCRIPTION_JOBS_LOCK:
        expired = [key for key, value in TRANSCRIPTION_JOBS.items() if now - float(value.get("updated_at", now)) > 3600]
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

    threading.Thread(
        target=_run_transcription_job,
        args=(job_id, audio_bytes, filename, content_type, requested_model),
        daemon=True,
        name=f"skate-transcription-{job_id[:8]}",
    ).start()
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
    ffmpeg_path = _find_local_ffmpeg()
    return {
        "ok": True,
        "whisper": bool(importlib.util.find_spec("whisper")),
        "decoder": bool(ffmpeg_path),
        "decoder_path": str(ffmpeg_path) if ffmpeg_path else "",
        "model_root": str(model_root),
        "models": model_files,
        "base_model": "base.pt" in model_files,
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
        payload = json.loads((await request.body()).decode("utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "Could not read the transcript."}

    title = str(payload.get("title", "")).strip() or "Untitled"
    transcript = str(payload.get("transcript", "")).strip()
    if not transcript:
        return {"ok": False, "error": "No transcript text found to summarize."}

    fallback = _local_transcript_summary(title, transcript)
    settings = _load_settings()
    if not _llm_available(settings):
        return {
            "ok": True,
            "summary": fallback,
            "markdown": _transcript_summary_markdown(fallback),
            "message": "No OpenAI API key is saved, so SKATE used local transcript summarization.",
        }

    try:
        response_text = _call_llm(settings, _transcript_summary_prompt(title, transcript))
        raw = _extract_json_object(response_text)
        summary = _normalize_transcript_summary(raw, fallback)
        summary["provider"] = settings["provider"]
        summary["model"] = settings["model"]
        return {
            "ok": True,
            "summary": summary,
            "markdown": _transcript_summary_markdown(summary),
            "message": f"Clean meeting notes added using {settings['provider']} / {settings['model']}.",
        }
    except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
        return {
            "ok": True,
            "summary": fallback,
            "markdown": _transcript_summary_markdown(fallback),
            "message": f"AI summarization failed, so SKATE used local transcript summarization. {e}",
        }


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
    fallback = _local_spotter_response(mode, text)
    settings = _load_settings()
    result = fallback
    message = ""

    if _llm_available(settings):
        try:
            session_context = _spotter_session_context(session, text)
            response_text = _call_llm(_feature_settings(settings, "spotter"), _spotter_prompt(mode, text, session_label or session, session_context, settings))
            result = _normalize_spotter_response(_extract_json_object(response_text), fallback, mode)
            result["provider"] = settings["provider"]
            result["model"] = settings["model"]
        except (ValueError, KeyError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError) as e:
            message = f"AI Spotter coaching failed, so SKATE used local coaching. {e}"
    else:
        message = "No OpenAI API key is saved, so SKATE used local Spotter coaching."

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
    # Keep the prompt bounded for very long workshops: most recent ~24k chars.
    transcript_tail = transcript[-24000:]

    settings = _load_settings()
    if not _llm_available(settings):
        return {"ok": False, "error": "No OpenAI API key is saved, so Spotter Live cannot answer."}

    name = settings.get("spotter_name", "Spotter")
    persona = settings.get("spotter_persona", "")

    def _live_prompt(include_persona: bool) -> str:
        persona_block = f"PERSONA (tone and expertise only — its output format rules do NOT apply):\n{persona}\n\n" if include_persona and persona else ""
        return (
            f"You are {name} Live, a real-time workshop copilot for a facilitator.\n"
            + persona_block
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
        answer = _spotter_live_clean_answer(_call_llm(_feature_settings(settings, "spotter"), _live_prompt(True)))
        if not answer and persona:
            # The persona's JSON formatting rules can win over the prose
            # instruction and yield {} — retry once without the persona.
            answer = _spotter_live_clean_answer(_call_llm(_feature_settings(settings, "spotter"), _live_prompt(False)))
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

    settings["provider"] = "openai"
    settings["model"] = model
    spotter_model = str(form.get("spotter_model", settings.get("spotter_model", ""))).strip()
    settings["spotter_model"] = spotter_model if spotter_model in valid_models else ""
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
    settings.setdefault("api_keys", {}).setdefault("openai", "")
    settings.setdefault("api_keys", {}).setdefault("elevenlabs", "")

    for key_provider in ("openai", "elevenlabs"):
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
    return TEMPLATES.TemplateResponse(request, "about.html", sidebar)


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


def _launch_with_tray(host: str, port: int, open_browser: bool, app_window: bool):
    """Launch SKATE with a system tray icon. Server runs in background thread."""
    try:
        import pystray
        from PIL import Image
    except ImportError as e:
        print(f"\n  WARNING: tray icon disabled ({e}).")
        print("  Install with: pip install pystray pillow")
        print("  Falling back to terminal-only mode.\n")
        _run_no_tray(host, port, open_browser, app_window)
        return

    url = f"http://{host}:{port}"
    icon_path = STATIC_DIR / "favicon.png"
    if not icon_path.exists():
        print(f"  WARNING: icon not found at {icon_path}, using default.")
        image = Image.new("RGBA", (64, 64), (46, 94, 142, 255))
    else:
        image = Image.open(icon_path)

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
        pystray.MenuItem(f"Running at {url}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit SKATE", on_quit),
    )

    icon = pystray.Icon(
        "SKATE",
        image,
        f"SKATE — Scalable Knowledge Architecture & Technology Engine\n{url}",
        menu,
    )

    print(f"\n  SKATE running at {url}")
    print(f"  Vault: {HERE.parent}")
    print(f"  Look for the skateboard icon in your Windows tray.\n")

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
