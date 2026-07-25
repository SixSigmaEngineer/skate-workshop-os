# SKATE — Tech Stack

A plain-language tour of what SKATE is built with and *why*. The guiding principles: **local-first**, **markdown-forever**, **no build step**, and **buy + wrap the hard parts** (models, voice) while owning the workflow and UX.

## Architecture direction

**Recommendation: keep this architecture.** SKATE already has the right shape for a competitive, testable MVP. The differentiated work is the memory model, workshop workflow, provenance, synthesis, and agent experience - not a migration to a fashionable front-end framework.

| Decision | Current direction | Steering guidance |
|---|---|---|
| Product category | Productivity and enterprise solutions | Lead with workshop synthesis, decision continuity, and organizational learning. |
| Primary AI path | Selectable provider: OpenAI (Responses API), Anthropic (Messages API), OpenRouter, local LM Studio, or none | Use it for typed memory candidates, relationship extraction, contradiction detection, and traceable synthesis. "None" keeps SKATE fully functional with deterministic local synthesis. |
| Coding workflow | AI-assisted development | Preserve meaningful sessions, commits, tests, and design decisions as engineering evidence. |
| Durable storage | Local Markdown + YAML frontmatter | Keep it. This is central to trust, portability, inspectability, and an Obsidian-compatible experience. |
| Web application | FastAPI + Jinja2 + vanilla JavaScript | Keep it for the hackathon. A React/Electron rewrite would add risk without strengthening the core story. |
| Retrieval | Hybrid lexical + local embeddings with graceful fallback | Add a small retrieval evaluation set before adding a vector database. |
| Agent connection | Read-only MCP over STDIO or Streamable HTTP | Keep tools bounded, governance-aware, and separate from unrestricted filesystem access. |
| Deployment | Local Windows app/server with a self-contained virtual environment | Provide double-click launchers, demo data, and clear judge instructions. Add hosted deployment only if it does not weaken the local-first promise. |

### Architecture guardrails

- **Do not replace Markdown with a database as the source of truth.** Add indexes or caches only as rebuildable acceleration layers.
- **Do not let generated memories silently become facts.** GPT-5.6 should propose; users should review consequential additions or changes.
- **Do not make the 3D graph decorative.** Use it to trace evidence, filter knowledge, expose conflicts, and select synthesis context.
- **Do not broaden the MVP into a complete Obsidian replacement.** Demonstrate one excellent loop: capture -> review -> connect -> synthesize -> retrieve.
- **Do not require cloud services for basic note access.** Core vault reading, graphing, and lexical retrieval should continue to work locally.
- **Do measure the product claim.** Track synthesis time, retrieval recall, evidence traceability, and at least one real-user reaction.

### Local server operations

- `Start SKATE.bat` creates `.venv` inside the repository, installs requirements when they change, starts FastAPI at `http://127.0.0.1:8765`, records its process ID, and opens the app.
- `Stop SKATE.bat` validates the recorded process before stopping it. It will not terminate an unrelated process if the ID has been reused.
- Runtime state (`.venv`, PID, logs, settings, and private workshop data) stays local through `.gitignore`.

---

## At a glance

| Layer | Technology |
|---|---|
| Language / runtime | Python 3.10–3.13 |
| Web framework | FastAPI (ASGI) |
| Server | Uvicorn |
| Templating | Jinja2 (server-rendered HTML) |
| Front end | Vanilla JavaScript + hand-written WebGL + SVG, hand-rolled CSS (no framework, no bundler) |
| Desktop shell | pywebview (native window) + pystray (system tray) |
| Data store | Markdown files + YAML frontmatter (no database) |
| Markdown / parsing | python-frontmatter, Markdown, Pygments |
| LLM provider | OpenAI GPT-5.6 through the Responses API |
| Agent protocol | Official MCP Python SDK; STDIO + Streamable HTTP |
| Voice | ElevenLabs (STT + TTS), optional local Whisper |
| Hardware control | Stream Deck Neo via global hotkeys |
| Packaging | Windows `.bat` launchers + venv; optional PyInstaller `.exe` |

---

## Backend

**FastAPI + Uvicorn.** The whole app is a single ASGI service (`ui/app.py`) that serves server-rendered pages and a small JSON API (`/api/spotter`, `/api/speak`, `/api/transcribe-audio`, …). FastAPI was chosen for speed of development, type-friendly request handling, and a tiny footprint for a single-user local app. HTTP calls to model/voice providers use the standard library (`urllib`) to keep the dependency surface small.

**Jinja2 templates.** Pages are rendered on the server (`ui/templates/`). There is deliberately no SPA framework — SKATE is a local tool, and server-rendered HTML keeps it simple, fast to load, and easy to reason about.

**`skate_lib.py`.** The domain core: it parses the markdown vault into `Entry` objects, performs lexical retrieval (keyword RAG) for Spotter's session memory, and builds the graph data (nodes + typed/relationship/theme edges) that powers The Grind.

---

## Data model — the markdown vault

There is **no database**. Each note is a `.md` file with YAML frontmatter:

- **Object type:** `type` (observation, pain, insight, recommendation, question, opportunity, …) drives node color and synthesis — the primary way the vault is organized.
- **Linking:** `relationships` (typed: references / causes / leads_to / contradicts / similar_to) and `themes` (shared themes create a similarity layer).
- **Scope:** `session` / `session_label` group notes into workshops.

Why markdown? It's portable, diff-able, git-able, human-readable, and Obsidian-compatible. The vault outlives any particular tool.

---

## Front end

**No framework, no build step.** Every page is plain HTML + a `<script>` block. This keeps the repo buildable by anyone with Python alone — no Node toolchain, no bundler, no `node_modules`.

**The Grind — custom WebGL.** The 3D knowledge graph is a hand-written WebGL renderer: custom GLSL vertex/fragment shaders for lit spheres and rails, a CPU force-directed physics layout, perspective projection, hit-testing for hover tooltips, and a 2D-canvas overlay for node labels that tracks the camera matrix. A pure-SVG renderer provides the 2D fallback view. No Three.js or graph library — it's all in `ui/templates/graph.html`.

**Styling.** Hand-rolled CSS in `ui/static/style.css`. Icons are inline SVGs.

---

## Desktop shell

SKATE can run as a real desktop app, not just a browser tab:

- **pywebview** renders the local site in a native OS window (Edge WebView2 on Windows).
- **pystray** puts SKATE in the system tray with a quit menu.
- **Pillow** generates/handles tray and window icons; **imageio-ffmpeg** supports media handling.

A `--browser` flag opens it in the default browser instead, and `--reload` runs the dev server with auto-reload.

---

## AI: language models

SKATE routes reasoning through a **selectable provider layer**: OpenAI GPT-5.6 (Responses API, with explicit reasoning effort), Anthropic Claude (Messages API), OpenRouter (any hosted model over an OpenAI-compatible endpoint), a local LM Studio server (OpenAI-compatible, fully on-machine), or **no AI at all** — in which case GRIND falls back to SKATE's deterministic local synthesis. With OpenAI selected, Spotter can use a separate GPT-5.6 model and reasoning level when lower latency is preferred during live facilitation.

Every Spotter response is built from a fixed base persona + a per-stance instruction + retrieved session notes, and returns structured JSON (spoken response, title, evidence, insights, recommendations, actions, questions, relationships).

---

## AI: voice

- **ElevenLabs** — Scribe for speech-to-text and low-latency TTS for spoken replies.
- **Local Whisper** — optional fully-offline transcription (heavier; off by default).

---

## Integrations

- **Stream Deck Neo** — each physical key is a global hotkey (`Ctrl+Alt+Shift+<key>`) that the web app listens for; 11 keys pre-prompt Spotter into coaching stances, the rest navigate. Icons and the hotkey map live in `streamdeck-neo-icons/`.
- **OneNote import** — dependency-light converters turn exported OneNote (.docx / .md / .html / .txt, optional .pdf via `pypdf`) into sessions and notes, with a dry-run preview.
- **MCP** — nine read-only tools expose active sessions, bounded hybrid retrieval, full memory objects, session context, typed evidence traces, and saved GRIND results. Local Codex uses STDIO; Secure MCP Tunnel or authenticated HTTPS connects ChatGPT Work on the web.

---

## Packaging & ops

- **Virtual environment** auto-created by the `.bat` launchers; deps pinned in `ui/requirements.txt`.
- The launchers self-heal a relocated/broken venv (a moved project folder breaks a venv's hard-coded paths) and verify dependencies in isolated mode.
- **PyInstaller** build (`build-app.ps1`) produces a standalone app.
- **No telemetry, no cloud sync.** Local-first by default; a cloud/sync path is on the roadmap.

---

## Key dependencies

```
fastapi            # web framework
uvicorn[standard]  # ASGI server (+ watchfiles for reload)
jinja2             # templates
python-frontmatter # YAML frontmatter parsing
markdown           # note rendering
pygments           # code highlighting
pystray            # system tray
pillow             # icons / images
pywebview          # native desktop window
imageio-ffmpeg     # media support
mcp                 # official Model Context Protocol SDK
# optional: pypdf (OneNote PDF import), openai-whisper (offline STT)
```

---

## Notable design choices

- **File-based, not database-backed** — the vault is the product's durable layer; markdown guarantees longevity and portability.
- **Server-rendered + vanilla JS** — zero front-end build complexity; anyone with Python can run it.
- **Hand-written WebGL** — full control over the "skate the rails" aesthetic without a heavyweight 3D dependency.
- **Deliberate model routing** — GRIND inherits the configured General GPT-5.6 model and reasoning level, while Spotter can use its own lower-latency GPT-5.6 route. Local Whisper remains available for private transcription, but it is not an LLM fallback.
