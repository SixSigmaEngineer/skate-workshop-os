# SKATE UI

A simple local web app for browsing your SKATE vault. No build step, no Node, no Electron. Just Python.

## What you get

- **Browse** all entries, sorted by date
- **Sessions and themes** sidebar with live entry counts
- **Grind graph** — explore typed relationships and shared themes between memory objects
- **Stats dashboard** — timeline and top tags
- **Search** by keyword and/or theme
- **Markdown rendering** with syntax highlighting, tables, and TOC

## Stack (all open source)

- **FastAPI** (Python) — local web server
- **Jinja2** — templating
- **python-frontmatter** — YAML frontmatter parsing
- **markdown** — Markdown → HTML rendering
- **Pico.css** — minimal CSS framework (loaded via CDN)

## First-time setup

```bash
cd SKATE/ui

# Create a virtual env (recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Run it

```bash
python app.py
```

What happens by default:

1. The web server starts on port 8765
2. A **skateboard icon appears in your Windows system tray** (notification area, bottom-right near the clock)
3. Your default browser opens to <http://localhost:8765> automatically

### Tray menu (right-click the skateboard icon)

- **Open SKATE** — opens the UI in your browser
- **Quit** — stops the server and removes the tray icon

### Options

```bash
python app.py --port 8888       # custom port
python app.py --no-tray         # run in terminal only (no tray icon)
python app.py --no-browser      # don't auto-open browser
python app.py --reload          # auto-reload on file changes (dev mode, disables tray)
python app.py --host 0.0.0.0    # accessible from other devices on your network
```

### Stopping SKATE

- **With tray:** right-click the skateboard → Quit
- **Without tray (`--no-tray`):** press `Ctrl+C` in the terminal

## How it works

1. On every page load, SKATE walks `../conversations/*.md`, parses YAML frontmatter, and renders.
2. No database. No build step. The vault on disk is the source of truth.
3. Edit any `.md` file directly — refresh the page and you see the change.

## Adding new entries

Use the existing CLI:

```bash
cd ..   # back to SKATE/
python tools/add_entry.py
```

The UI auto-picks up the new entry on the next page load. No re-indexing required.

## Architecture notes

- `app.py` — FastAPI routes (thin)
- `skate_lib.py` — read/parse logic (testable, framework-free)
- `templates/` — Jinja2 templates
- `static/style.css` — custom styling on top of Pico.css

## What's next (Phase 2)

- In-app editing
- AI-powered classification (calls the configured LLM to suggest themes, tags, and type for new entries)
- Vector search (embeddings via OpenAI or local model + Chroma)

## Troubleshooting

**"ModuleNotFoundError: fastapi"** — you didn't install deps. Run `pip install -r requirements.txt`.

**"Address already in use"** — port 8765 is taken. Run with `--port 8888` or kill the other process.

**Sidebar shows zero entries** — your vault path may be wrong. The app expects to find conversations at `../conversations/` relative to `app.py`. Confirm SKATE folder structure is intact.
