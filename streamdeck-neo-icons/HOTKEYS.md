# SKATE Spotter — Stream Deck Neo macro map

These macros drive **Spotter**, the voice coaching agent, during live workshops.

**How a macro works:** each prompt key *pre-prompts* Spotter into a coaching stance
(Observe, Find Waste, 5 Whys, etc.) **and** opens the microphone in one press. You talk,
Spotter listens in that stance, then responds. The two touch points just start and stop
the mic without changing stance. The agent only listens while the mic is open, so nothing
is captured between presses.

Every macro is a Stream Deck **Hotkey** action. The SKATE web app listens for the same
keyboard shortcut, so the physical key and the on-screen behavior stay in sync. The Spotter
page must be open and focused for the prompt keys to fire.

**Modifier stack for every key:** `Ctrl + Alt + Shift` + the listed key.

---

## Recommended Neo layout (physical workshop)

The Neo has **8 keys** (2 rows × 4) plus **2 touch points** beside the info bar.
Put the talk controls on the touch points and the 8 highest-value stances on the keys.

### Touch points (left / right of the screen)

| Position | Icon | Hotkey | Action |
| --- | --- | --- | --- |
| Left touch point | `start-talking.svg` | Ctrl+Alt+Shift+Space | **Start talking** — open the mic in the current stance |
| Right touch point | `stop-talking.svg` | Ctrl+Alt+Shift+X | **Stop talking** — close the mic and send to Spotter |

### 8 keys

| Key | Icon | Hotkey | Stance — what Spotter does with your voice |
| --- | --- | --- | --- |
| 1 | `prompt-observe.svg` | Ctrl+Alt+Shift+O | **Observe** — capture what people do, say, feel, and work around |
| 2 | `prompt-find-waste.svg` | Ctrl+Alt+Shift+W | **Find Waste** — listen for delay, rework, handoffs, motion, waiting |
| 3 | `prompt-five-whys.svg` | Ctrl+Alt+Shift+Y | **5 Whys** — drive a root-cause chain from the symptom you describe |
| 4 | `prompt-hmw.svg` | Ctrl+Alt+Shift+H | **How Might We** — reframe the pain into strong HMW prompts |
| 5 | `prompt-process-map.svg` | Ctrl+Alt+Shift+M | **Map Flow** — turn the spoken flow into trigger, handoffs, queues, decisions |
| 6 | `prompt-frame-challenge.svg` | Ctrl+Alt+Shift+F | **Frame Challenge** — sharpen a raw pain into a clear problem statement |
| 7 | `prompt-synthesize-notes.svg` | Ctrl+Alt+Shift+Z | **Synthesize** — connect patterns across the active session's notes |
| 8 | `prompt-executive-readout.svg` | Ctrl+Alt+Shift+R | **Readout** — convert the moment into an exec-ready insight + next step |

> Tip: build a second Neo page for the swap-ins below if a session leans more toward
> kaizen planning or experiment design.

---

## Full hotkey reference

### Spotter voice keys (Spotter page only)

| Icon | Hotkey | Action |
| --- | --- | --- |
| `start-talking.svg` | Ctrl+Alt+Shift+Space | Start talking (open mic) |
| `stop-talking.svg` | Ctrl+Alt+Shift+X | Stop talking (close mic, send) |
| `prompt-observe.svg` | Ctrl+Alt+Shift+O | Wake as **Observe** and start listening |
| `prompt-frame-challenge.svg` | Ctrl+Alt+Shift+F | Wake as **Frame Challenge** and start listening |
| `prompt-hmw.svg` | Ctrl+Alt+Shift+H | Wake as **How Might We** and start listening |
| `prompt-five-whys.svg` | Ctrl+Alt+Shift+Y | Wake as **5 Whys** and start listening |
| `prompt-kaizen.svg` | Ctrl+Alt+Shift+K | Wake as **Kaizen Event** and start listening |
| `prompt-process-map.svg` | Ctrl+Alt+Shift+M | Wake as **Process Map** and start listening |
| `prompt-find-waste.svg` | Ctrl+Alt+Shift+W | Wake as **Find Waste** and start listening |
| `prompt-synthesize-notes.svg` | Ctrl+Alt+Shift+Z | Wake as **Synthesize Notes** and start listening |
| `prompt-next-experiment.svg` | Ctrl+Alt+Shift+T | Wake as **Next Experiment** and start listening |
| `prompt-executive-readout.svg` | Ctrl+Alt+Shift+R | Wake as **Executive Readout** and start listening |
| `prompt-ask-spotter.svg` | Ctrl+Alt+Shift+Q | Wake as **Ask Spotter** (free question) and start listening |

### Global navigation keys (work anywhere in SKATE)

| Icon | Hotkey | Action |
| --- | --- | --- |
| `library-skateboard.svg` | Ctrl+Alt+Shift+L | Open Library |
| `start-skate.svg` | Ctrl+Alt+Shift+N | New Note |
| `grind-rail.svg` | Ctrl+Alt+Shift+G | Open GRIND |
| `spotter.svg` | Ctrl+Alt+Shift+P | Open Spotter |
| `sessions-skate.svg` | Ctrl+Alt+Shift+S | Open Sessions |
| `skate-mark.svg` | Ctrl+Alt+Shift+A | Open About SKATE |

---

## Stream Deck setup notes

1. Add a **Hotkey** action to each key and record the exact combination above
   (hold `Ctrl + Alt + Shift`, then tap the letter / Space / X).
2. Set the key image to the matching `.svg` in this folder.
3. Open SKATE, go to **Spotter** (Ctrl+Alt+Shift+P), and leave that window focused
   during the workshop — the prompt keys only fire there.
4. Select a **Session** in the "Session memory" field (or open
   `/spotter?session=client-workshop`) so stances like Synthesize and Readout can
   reason over that session's captured notes.
5. Workflow in the room: tap a **stance key** (mic opens) → talk → tap **Stop talking**
   (right touch point) → Spotter responds and the exchange logs in the chat. Use
   **Start talking** (left touch point) to keep dictating in the same stance.

Icons are hand-designed **SVG** files in this folder. Stream Deck accepts SVG directly, so
just point each key's image at the matching `.svg` — there is no regeneration step or
Python dependency. To restyle the whole set, edit the shared background (`#16202C`) or glyph
color (`#FFFFFF`) in any file.
