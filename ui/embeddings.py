"""
SKATE semantic retrieval — local-first, open-source embeddings with hybrid scoring.

Backends, auto-detected in order (all optional — SKATE degrades gracefully to
lexical-only search when none is available):

  1. ollama    — local Ollama server (MIT) with an Apache-2.0 embedding model
                 (default: nomic-embed-text). Best quality/speed on a GPU box.
                 Install: https://ollama.com  then  `ollama pull nomic-embed-text`
  2. fastembed — Qdrant's fastembed (Apache 2.0), ONNX on CPU, pip-installable,
                 no external server.  `pip install fastembed`
  3. openai    — text-embedding-3-small, available only when explicitly
                 selected with SKATE_EMBED_BACKEND=openai. It is never an
                 automatic fallback because that would send vault text to a
                 cloud service without a retrieval-specific opt-in.

Override with env SKATE_EMBED_BACKEND = ollama | fastembed | openai | off
and SKATE_EMBED_MODEL (backend-specific model name).

Embeddings are cached on disk by content hash (SKATE_ROOT/.cache/embeddings/),
so a vault is only ever embedded once per backend+model. Vector math is pure
stdlib — at SKATE vault sizes (10s–100s of notes) cosine over cached vectors
takes microseconds; no vector database is needed or wanted.

Hybrid scoring: 60% semantic cosine similarity + 40% normalized lexical score.
Lexical keeps exact-term precision (names, jargon); semantic closes the
synonym gap ("cost" ↔ "pricing", "ramp time" ↔ "onboarding").
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import skate_lib
from skate_lib import Entry

CACHE_DIR = skate_lib.SKATE_ROOT / ".cache" / "embeddings"

OLLAMA_URL = os.environ.get("SKATE_OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODELS = {
    "ollama": "nomic-embed-text",
    "fastembed": "BAAI/bge-small-en-v1.5",
    "openai": "text-embedding-3-small",
}

HYBRID_SEMANTIC_WEIGHT = 0.6


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------


class _Backend:
    name = "none"
    model = ""

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        raise NotImplementedError


class _OllamaBackend(_Backend):
    name = "ollama"

    def __init__(self, model: str):
        self.model = model

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        # nomic-embed-text is trained with task prefixes.
        prefix = "search_query: " if kind == "query" else "search_document: "
        if "nomic" in self.model:
            texts = [prefix + t for t in texts]
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["embeddings"]


class _FastembedBackend(_Backend):
    name = "fastembed"

    def __init__(self, model: str):
        from fastembed import TextEmbedding  # noqa: PLC0415

        self.model = model
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        return [list(map(float, vec)) for vec in self._model.embed(texts)]


class _OpenAIBackend(_Backend):
    name = "openai"

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self._key = api_key
        self._base = base_url.rstrip("/")

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [item["embedding"] for item in data["data"]]


def _openai_key() -> tuple[str, str]:
    key = os.environ.get("OPENAI_API_KEY", "")
    base = "https://api.openai.com/v1"
    settings_path = skate_lib.SKATE_ROOT / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            key = key or settings.get("api_keys", {}).get("openai", "")
            base = settings.get("openai_base_url", base) or base
        except (OSError, json.JSONDecodeError):
            pass
    return key, base


_backend: Optional[_Backend] = None
_backend_resolved = False


def _make_backend(name: str, model: str) -> Optional[_Backend]:
    try:
        if name == "ollama":
            backend = _OllamaBackend(model or DEFAULT_MODELS["ollama"])
            backend.embed(["ping"], "query")  # verify server + model actually work
            return backend
        if name == "fastembed":
            return _FastembedBackend(model or DEFAULT_MODELS["fastembed"])
        if name == "openai":
            key, base = _openai_key()
            if not key:
                return None
            return _OpenAIBackend(model or DEFAULT_MODELS["openai"], key, base)
    except Exception:
        return None
    return None


def get_backend() -> Optional[_Backend]:
    """Detect and cache the best available embedding backend (or None)."""
    global _backend, _backend_resolved
    if _backend_resolved:
        return _backend
    forced = os.environ.get("SKATE_EMBED_BACKEND", "").strip().lower()
    model = os.environ.get("SKATE_EMBED_MODEL", "").strip()
    if forced == "off":
        _backend = None
    elif forced:
        _backend = _make_backend(forced, model)
    else:
        for name in ("ollama", "fastembed"):
            _backend = _make_backend(name, model)
            if _backend is not None:
                break
    _backend_resolved = True
    return _backend


def backend_status() -> dict:
    backend = get_backend()
    if backend is None:
        return {"semantic": False, "backend": None, "model": None,
                "note": "lexical-only; install Ollama (+ `ollama pull nomic-embed-text`) or `pip install fastembed` to enable semantic search"}
    return {"semantic": True, "backend": backend.name, "model": backend.model}


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


def _cache_path(backend: _Backend) -> Path:
    safe = f"{backend.name}-{backend.model}".replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def _load_cache(backend: _Backend) -> dict[str, list[float]]:
    path = _cache_path(backend)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_cache(backend: _Backend, cache: dict[str, list[float]]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(backend).write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _note_repr(entry: Entry) -> str:
    """The text that represents a note in embedding space."""
    return " | ".join(
        part for part in [
            entry.title,
            " ".join(entry.themes),
            " ".join(entry.tags),
            (entry.summary or entry.body or "")[:800],
        ] if part
    )


def semantic_scores(query: str, entries: list[Entry]) -> Optional[dict[str, float]]:
    """Cosine similarity of query vs each entry, keyed by entry path.
    Returns None when no backend is available (caller falls back to lexical)."""
    backend = get_backend()
    if backend is None or not query.strip() or not entries:
        return None
    try:
        cache = _load_cache(backend)
        reprs = {str(e.path): _note_repr(e) for e in entries}
        missing = [(k, t) for k, t in reprs.items() if _hash(t) not in cache]
        if missing:
            vectors = backend.embed([t for _, t in missing], "document")
            for (_, text), vec in zip(missing, vectors):
                cache[_hash(text)] = vec
            _save_cache(backend, cache)
        qvec = backend.embed([query], "query")[0]
        return {k: cosine(qvec, cache[_hash(t)]) for k, t in reprs.items()}
    except Exception:
        return None  # any backend hiccup → lexical fallback, never a crash


def rank_entries(
    entries: list[Entry],
    query: str,
    lexical_score: Callable[[Entry], float],
    top_k: int = 5,
) -> tuple[list[Entry], str]:
    """Hybrid ranking used by Spotter context.

    Blends normalized semantic cosine (weight 0.6) with normalized lexical
    score (0.4). Falls back to lexical-only, then to recency. Returns
    (top entries, mode) where mode is 'hybrid', 'lexical', or 'recent'.
    """
    if not entries:
        return [], "recent"
    lex = {str(e.path): float(lexical_score(e)) for e in entries}
    max_lex = max(lex.values()) or 1.0
    sem = semantic_scores(query, entries)

    if sem is not None:
        w = HYBRID_SEMANTIC_WEIGHT
        blended = sorted(
            entries,
            key=lambda e: (
                w * sem.get(str(e.path), 0.0) + (1 - w) * (lex[str(e.path)] / max_lex),
                e.date,
            ),
            reverse=True,
        )
        return blended[:top_k], "hybrid"

    scored = sorted(entries, key=lambda e: (lex[str(e.path)], e.date), reverse=True)
    top = [e for e in scored if lex[str(e.path)] > 0][:top_k]
    if top:
        return top, "lexical"
    recent = sorted(entries, key=lambda e: e.date, reverse=True)[: max(3, top_k - 1)]
    return recent, "recent"
