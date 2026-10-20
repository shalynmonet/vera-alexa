# Vera

A warm wellness companion for older adults, built for Alexa+. Vera keeps minds and bodies busy with a memory game, a guided chair stretch, and guided meditation, and celebrates progress with a visual fitness log of streaks and milestones. Caregivers get a simple daily summary.

Vera is named after my late great-grandmother and inspired by caring for my grandmother.

## How it works

Vera is a **self-hosted MCP server** (spec `2025-11-25`, Streamable HTTP), the open standard behind Alexa+ integrations. An Alexa+ experience (or the included web simulator) calls Vera's tools to run sessions and read progress.

| Tool | What it does |
|---|---|
| `get_profile`, `set_profile` | Preferred name and weekly goal |
| `start_memory_game` | Picks 3 to 6 familiar words for Vera to read aloud |
| `submit_memory_answer` | Scores the spoken answer (forgiving of order and mishearings), adapts difficulty, logs the game |
| `list_sessions` | Available stretch routines and meditations |
| `start_stretch_routine` | Seated stretch video plus step by step narration with a halfway check in |
| `start_meditation` | 3 min, 10 min, or bedtime meditation |
| `log_completion` | Records a finished stretch or meditation, returns streak and new milestones |
| `get_fitness_log` | Calendar grid, totals, streak, weekly goal, badges |
| `get_streak` | Current and longest streak |
| `check_milestones` | Awards any newly earned badges |
| `get_daily_summary` | Caregiver friendly summary of the day |

**Design choices for older users:** every activity counts toward the streak, one missed day is forgiven (grace day), and missed days are never framed as failures.

Every tool accepts an optional `on_date` (YYYY-MM-DD) so demos and tests can use a fixed date.

## Run it (Windows PowerShell)

```powershell
cd vera-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python seed_demo.py --name Rose   # optional: 4 weeks of demo history
python server.py                  # http://127.0.0.1:8000/mcp
```

If activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### Try the tools in MCP Inspector

```powershell
npx @modelcontextprotocol/inspector
```

Choose transport **Streamable HTTP**, URL `http://127.0.0.1:8000/mcp`, then Connect.

### Tests

```powershell
python -m pytest -q
```

Includes an end to end test that starts the server and calls every core tool through the official MCP client over Streamable HTTP.

## Configuration

| Env var | Default | |
|---|---|---|
| `VERA_HOST` | `127.0.0.1` | Use `0.0.0.0` when hosting |
| `VERA_PORT` | `8000` | |
| `VERA_DATA` | `data/vera.json` | JSON store |
| `VERA_CORS_ORIGINS` | `*` | Lock down for production |

## Roadmap

- Web based Alexa+ simulator with Echo Show style screens
- AWS Bedrock powered conversation layer
- Optional check in calls and caregiver reports

## License

MIT
