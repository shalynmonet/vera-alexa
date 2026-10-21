# Vera

A warm wellness companion for older adults, built for Alexa+. Vera keeps minds and bodies busy with a memory game, a guided chair stretch, and guided meditation, and celebrates progress with a visual fitness log of streaks and milestones. Caregivers get a simple daily summary.

Vera is named after my late great-grandmother and inspired by caring for my grandmother.

## How it works

Vera is a **self-hosted MCP server** (spec `2025-11-25`, Streamable HTTP), the open standard behind Alexa+ integrations. An Alexa+ experience (or the included web simulator) calls Vera's tools to run sessions and read progress.

| Tool | What it does |
|---|---|
| `get_profile`, `set_profile` | Preferred name and weekly goal |
| `list_profiles`, `create_profile` | Everyone sharing this Vera, for the start screen's profile picker |
| `start_memory_game` | Picks 3 to 6 familiar words for Vera to read aloud |
| `submit_memory_answer` | Scores the spoken answer (forgiving of order and mishearings), adapts difficulty, logs the game |
| `list_sessions` | Available games, stretch routines, and meditations |
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

## Web simulator

An Echo Show style Alexa+ simulator in the browser, matching the look of the
[Vera Cares](https://vera-cares.lovable.app/) site: big text, high contrast,
large buttons, and a natural chat layer (AWS Bedrock, Amazon Nova Lite via
the Converse API) that calls Vera's MCP tools through tool use. If Bedrock
isn't reachable or configured, the simulator falls back to simple keyword
routing so it keeps working.

Vera speaks with Amazon Polly: a warm neural voice, read slightly slower
(SSML prosody) for older ears, generated once per line and cached on disk
(`web/audio_cache/`, gitignored) so repeated lines are instant. Her mouth is
lip-synced to the actual audio -- a Web Audio analyser watches playback
volume and swaps `vera-talking.webp`/`vera-talking-closed.webp` in real
time. If Polly isn't configured or a request fails, the browser's own
SpeechSynthesis takes over automatically, with a timed mouth-flap
approximation (that API exposes no audio to analyse). Voice *input* stays
the browser's SpeechRecognition either way, with the type-to-talk fallback
for when that isn't available.

A start screen lets each person in the household pick their own profile
("Continue as Rose" / "Add a person") -- like Alexa's voice profiles on a
shared Echo -- so progress is kept separately per person. The choice is
remembered per device (localStorage), so future visits skip straight to
Home; tapping "Not you? Switch person" brings the picker back. From there,
home has four sections -- Games, Exercise, Meditations, Progress -- each
backed by its own MCP tool(s) so new games or routines show up
automatically.

Vera herself is a persistent on-screen companion (a purple elephant) built
from `web/static/js/companion.js`: large and centered on the start/home
screens with a speech bubble for her words, a small corner companion on
activity screens, shrinking and dimming during a video or meditation
session, and animating to center stage to celebrate a new milestone. Each
section has its own idle pose (thinking for Games, exercising for Exercise,
meditating for Meditations, celebrating for Progress), with a gentle idle
bob and talk/celebrate bounce that respects `prefers-reduced-motion`. Poses
are plain images today; the module is structured so any pose can later
become a looping video without touching call sites.

```powershell
# with the Vera MCP server already running (see above)
pip install -r requirements.txt
python -m web.app   # http://127.0.0.1:8080
```

Configuration (env vars): `VERA_MCP_URL` (default `http://127.0.0.1:8000/mcp`),
`WEB_HOST` / `WEB_PORT` (default `127.0.0.1:8080`), `VERA_BEDROCK_MODEL_ID`
(default `us.amazon.nova-lite-v1:0`), `VERA_POLLY_VOICE` (default `Joanna`),
`VERA_POLLY_ENGINE` (default `neural`), `VERA_POLLY_RATE` (default `92%`),
`AWS_REGION` (default `us-east-1`). Needs AWS credentials (e.g. via
`aws configure`) with `bedrock:InvokeModel` and `polly:SynthesizeSpeech`.

## Roadmap

- Optional check in calls and caregiver reports

## License

MIT
