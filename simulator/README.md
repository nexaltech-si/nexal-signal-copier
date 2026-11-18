# Signal Simulator

Replays historical Telegram messages through the **exact same pipeline** as the live bot:

```
AI intent classification → pre-filter → AI/vision/pattern extraction
  → context resolution → TradingBrain review → aggregated stats
```

No trade execution — purely diagnostic.

---

## Modes

### 1. Dashboard (primary)

Open **Simulator** in the dashboard sidebar. The simulator runs inside the bot process and **shares the live Telegram client** — no second login, no session conflict.

Controls:
- Channel, date range, message limit, TradingBrain toggle
- Real-time log stream over SSE (Server-Sent Events)
- Stats cards, symbol distribution, error breakdown
- Saved results browser (download / delete JSON files)

### 2. CLI (standalone)

Use when the live bot is not running. Opens its own Telegram session AND its
own database connection (same SQLite file/Prisma schema as the bot) to load
the exact same AI config the live bot would use.

```bash
# Interactive — pick channel, date range, limit
python -m simulator.cli

# Batch — all broadcast channels visible to this Telegram account
python -m simulator.cli --mode batch

# Enable TradingBrain review (costs API calls per signal)
python -m simulator.cli --brain
```

The CLI uses its own Telegram session (`simulator_session`) authenticated from
`.env` credentials (`TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE`).

---

## Configuration

**There is no config file, and AI config is never read from `.env` directly.**
Every AI/pipeline setting — provider, vision provider, models, fallback
chain, vision filters — comes from the **database**, the same source the
live bot reads via `settings.reload_from_db()`. This is deliberate: an
earlier version re-derived a separate config from raw `.env` values, which
silently diverged from what was configured in the dashboard (it resolved the
vision provider to `PRIMARY_AI_PROVIDER`, e.g. "deepseek" — which has no
vision support — instead of the database-configured vision provider, e.g.
"gemini"). Every image-only signal failed as a result. There is no fallback
to `.env` anymore: if the database config can't be loaded, the simulator
fails loudly instead of silently running with the wrong AI settings.

| What | Where it comes from |
|------|---------------------|
| Telegram channels | Live client's dialogs cache (same as Telegram Browser) |
| Discord channels | The channels selected on the Discord page, grouped under `Discord · Server · Category`; history is read through the live Discord connection, nothing is stored |
| AI provider / vision provider / models / fallbacks | **Database** — `signal_service.ai_config` (dashboard mode) or a CLI-local DB connection (standalone mode) |
| Date range, message limit, brain toggle | Selected in the dashboard UI (or CLI flags) |
| Telegram session | Shared from the live bot (dashboard mode) or its own session (CLI mode) |
| Telegram credentials (CLI only) | `.env` — `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` (needed to open a session at all; not AI config) |

---

## Architecture

```
simulator/
├── models.py    # SimulatedTrade + SimulationResults dataclasses
├── engine.py    # TradingSimulator — core pipeline, accepts shared TelegramClient
├── service.py   # SimulatorService singleton — run/stop, SSE event queue, results
├── api.py       # FastAPI router at /api/simulator/* + SSE /api/simulator/events
├── cli.py       # Standalone CLI entry point — loads AI config from the database
└── analyzer.py  # Post-run results analysis helpers
```

**Shared client flow:**

```
main.py → TelethonListener.start()
             → authenticates Telegram
             → simulator_service.set_telegram_client(client)  ← injected here
```

When a simulation is started from the dashboard, `SimulatorService` passes this shared client to `TradingSimulator`, so no second Telegram session is opened.

---

## API endpoints

All mounted on the FastAPI server (port 8001):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/simulator/status` | Current state + live progress |
| POST | `/api/simulator/run` | Start a simulation |
| POST | `/api/simulator/stop` | Cancel running simulation |
| GET | `/api/simulator/results` | List saved result files |
| GET | `/api/simulator/results/{file}` | Fetch a result JSON |
| DELETE | `/api/simulator/results/{file}` | Delete a result file |
| GET | `/api/simulator/events` | SSE real-time event stream |

---

## Results

Saved to `simulator/results/{channel}_{timestamp}.json`. Each file contains the full `SimulationResults` payload including per-message `trades` array.

Key fields in the summary:

| Field | Description |
|-------|-------------|
| `total_messages` | Messages fetched from Telegram |
| `intent_signal_count` | AI-classified as SIGNAL |
| `ai_extracted_count` | Extracted by AI processor |
| `pattern_extracted_count` | Extracted by pattern matching |
| `image_extracted_count` | Extracted via vision AI |
| `failed_extraction_count` | Nothing extracted |
| `open_signals` | OPEN actions |
| `brain_approved` | TradingBrain approved (if enabled) |
| `symbol_distribution` | Counts per symbol |
| `common_errors` | Top extraction errors |

---

## Analyzer

`analyzer.py` provides `ResultsAnalyzer` for deeper post-run inspection:

```python
from simulator.analyzer import ResultsAnalyzer

ra = ResultsAnalyzer()
data = ra.load_results("MyChannel_20250617_120000.json")
patterns = ra.analyze_extraction_patterns(data)
symbols  = ra.analyze_symbol_accuracy(data)
actions  = ra.analyze_action_accuracy(data)
```
