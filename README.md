# Vera

A warm wellness companion for older adults, built for Alexa+. Vera keeps minds and bodies busy with four games, guided exercise routines, and guided meditation, and celebrates progress with a visual fitness log of streaks and milestones. Family members can leave her short audio/video cheers to play at just the right moment, and caregivers get a simple daily summary.

Vera is named after my late great-grandmother and inspired by caring for my grandmother -- specifically, by how much of caregiving is just noticing: did she move today, did she eat, is she lonely, is anyone keeping track. I built Vera to be the thing quietly keeping track, so a family doesn't have to ask about it every day, and so the person at the center of it all gets encouragement instead of a checklist.

**On Alexa+, Vera uses the customer's Amazon account identity automatically** -- there are no accounts, logins, or passwords anywhere in this app. A household's Alexa+ voice profiles map onto Vera's own per-person profiles; a family member's cheer-recording link works from a single private, unguessable URL, nothing to sign into.

## Architecture

```
  Alexa+ (voice, on-device identity)  ───┐
                                          │  MCP tools, Streamable HTTP
  Web simulator (browser, dev/demo)  ────┤  (same tools, either caller)
                                          ▼
                     ┌────────────────────────────────────┐
                     │          Vera MCP Server            │
                     │            (server.py)              │
                     │  games · fitness log · memories ·   │
                     │  milestones · family cheers          │
                     └─────────────┬──────────────┬────────┘
                                   │              │
                          data/vera.json    presigned URLs
                           (JSON store)            │
                                                    ▼
                                           ┌─────────────────┐
                                           │    Amazon S3     │
                                           │ (media, cheers)  │
                                           └─────────────────┘

  The web simulator also calls these directly, standing in for what
  Alexa+ provides natively on-device:

    Amazon Bedrock (Nova Lite) -- conversational tool-use loop, greeting
    Amazon Polly               -- text to speech
    Amazon SES                 -- optional caregiver nudge emails
```

Vera is a **self-hosted MCP server** (spec `2025-11-25`, Streamable HTTP), the open standard behind Alexa+ integrations. In production, Alexa+ calls the MCP server's tools directly, using its own voice recognition, text to speech, and language model -- Vera never has to know any of that is happening.

The included **web simulator** (`web/app.py`) exists so this could be built and demoed before any real Alexa+ integration: it plays the part of Alexa+ in the browser, recreating that pipeline locally with Amazon Bedrock (Nova Lite, for the conversational tool-use loop and the proactive greeting) and Amazon Polly (for speech). It's a development and demo harness, not a second product -- every feature it shows off is really just calling the same MCP tools Alexa+ would call.

## MCP Tools

| Tool | What it does |
|---|---|
| `get_profile`, `set_profile` | Preferred name and weekly goal |
| `list_profiles`, `create_profile` | Everyone sharing this Vera, for the start screen's profile picker |
| `start_memory_game` | Picks 3 to 6 familiar words for Vera to read aloud |
| `submit_memory_answer` | Scores the spoken answer (forgiving of order and mishearings), adapts difficulty, logs the game |
| `start_matching_game` | Deals 6 to 12 cards (large pictures) for a flip-to-match round; difficulty is the pair count |
| `submit_matching_result` | Logs a finished matching round from how many flips it took, adapts difficulty |
| `start_saying_game` | Starts a "Finish the Saying" round (classic proverbs, multiple choice); difficulty is sayings per round |
| `submit_saying_answer` | Grades one answer and returns the next question, or the final score once the round is done |
| `start_category_game` | Starts a word categories round (name things in a category); difficulty is the target item count |
| `submit_category_answer` | Scores a free-form list of named items forgivingly, adapts difficulty, logs the game |
| `list_sessions` | Available games, exercise routines, and meditations, each flagged whether its real recording exists yet |
| `start_stretch_routine` | A guided exercise routine (chair stretch, seated strength, balance, gentle walking): real video if recorded, step by step narration either way |
| `start_meditation` | A guided meditation: real audio/video if recorded, or an intro line and target length otherwise |
| `log_completion` | Records a finished guided stretch/exercise or meditation session, returns streak and new milestones |
| `log_activity` | Logs a self-reported activity with no guided session -- a walk, bike or stationary bike ride, gardening, dancing, swimming, or anything else by name -- toward the same streak, goal, and milestones |
| `get_fitness_log` | Calendar grid, totals, streak, weekly goal (days and minutes), badges |
| `get_streak` | Current and longest streak |
| `check_milestones` | Awards any newly earned badges |
| `get_daily_summary` | Caregiver friendly summary of the day, including self-reported activities |
| `remember_fact` | Saves a meaningful personal detail (family, hobbies, upcoming events) to bring up again later; refuses health details |
| `get_memories` | Recent personal facts, most recent first, for Nova to naturally bring one up in conversation |
| `list_family`, `add_family_member`, `remove_family_member` | Family members who can record cheers, each with a private record-link token |
| `resolve_family_token` | Looks up who a private record-page link belongs to and who it's for |
| `upcoming_milestones` | Milestones the person is one step away from, each with a ready-made "almost there" nudge |
| `save_cheer`, `list_cheers`, `get_cheer`, `mark_cheer_played` | Save, browse, fetch, and mark-played the audio/video cheers family members record |

**Design choices for older users:** every activity counts toward the streak, one missed day is forgiven (grace day), and missed days are never framed as failures.

### Games

Four games, each with its own logic module (`vera/memory_game.py`, `matching_game.py`,
`saying_game.py`, `word_categories.py`), adaptive difficulty, and self-logging
to the fitness log:

- **Memory Game** -- Vera reads a short list of words; say or type back as many as you remember.
- **Matching Pairs** -- flip cards (6 to 12, large pictures) to find the matches.
- **Finish the Saying** -- classic proverbs, multiple choice, one question at a time.
- **Word Categories** -- name as many things as you can in a category (fruits, animals, colors, furniture, vegetables), scored forgivingly like the memory game.

Playing all four at least once earns the "Tried Every Game" badge.

### Memories and the proactive greeting

Vera remembers meaningful personal details shared in conversation -- family, hobbies,
upcoming events -- via `remember_fact` (`vera/memories.py`), stored per user in the
same JSON store as everything else. A keyword backstop refuses anything
health-related (diagnoses, medications, symptoms) even if asked to save it,
on top of the system prompt telling Nova never to try; in testing, Nova
never even attempted it. `get_memories` lets Nova recall one later, e.g.
"Last time you said your granddaughter had a volleyball game -- how did it go?"

When the app opens, Vera greets the person by name before being asked --
once per session/profile, not on every visit to Home -- using the same
Bedrock tool loop as regular chat: she calls `get_daily_summary` for streak
and recent milestones, `get_memories` for one personal detail, mentions any
milestone she's close to, and suggests one activity (without starting it).
If Bedrock isn't configured, Home falls back to the simple streak-based
greeting from Day 2.

### Exercise and meditation media

Real videos and audio are described by a hand-edited `manifest.json` next to each category (title, minutes, file, thumbnail, and for exercise, narration steps). `vera/media.py` resolves each manifest entry's file to a playable URL -- from the S3 bucket if one's configured and the file has been uploaded there, otherwise from local disk -- and reports the routine as `available` only once the file actually exists somewhere, so a routine with no recording yet simply shows a friendly "coming soon" card. No code change is needed either way: drop the file in locally, or upload it to the bucket, with the exact filename the manifest expects. The four exercise routines (chair stretch, seated strength, balance, gentle walking) ship as narration-only placeholders today; meditations are built from whatever real files already exist (currently one: "Healing Affirmations"). See [Media storage](#media-storage-local-vs-s3) below for the folder/bucket layout.

### Logging any activity, three ways

Beyond the guided sessions, three ways to log an unguided activity (walk, bike, stationary bike, gardening, dancing, swimming, or anything else by name) all land on the same `log_activity` tool:

1. **Voice, through Nova** -- "I walked for 20 minutes" or "I did half an hour of gardening."
2. **Log an Activity button** (on the Exercise screen) -- pick the activity, then minutes (5 to 60), then an optional feeling.
3. **Start a Walk / Start a Ride** (also on Exercise) -- a live stopwatch; Vera checks in every few minutes, and tapping "I'm Done" logs the elapsed time automatically.

Every tool accepts an optional `on_date` (YYYY-MM-DD) so demos and tests can use a fixed date.

### Family Cheers

Family members can record a short audio or video cheer for the person using
Vera, with no account or login of their own. From the caregiver dashboard
(`/caregiver/<user_id>`, linked from the Progress screen), add a family
member's name, relationship, and optional email; each gets a unique, private
record-page link (`/cheer/<token>`) built around `secrets.token_urlsafe`
(`vera/family.py`) -- the token itself is the only thing that page knows
them by.

The record page (`web/static/cheer/record.html`, `web/static/js/cheer-record.js`)
is a single large Record button (browser `MediaRecorder`, audio or video, 30
seconds max), with preview, re-record, and Send. A cheer can be attached to
one of the person's upcoming milestones (`upcoming_milestones` finds
milestones they're one step away from -- "1 day away", "about 10 minutes
away" -- and writes a ready-made nudge like "Rose is 1 day away from their 7
Day Streak! Record a cheer and Vera will play it the moment she gets
there"), or saved as an "anytime" cheer for a backup bank.

The dashboard shows the daily summary, each upcoming milestone's nudge with
a copyable record link per family member, and the family list. With Amazon
SES configured (sandbox mode -- sender and every recipient must be verified
identities), it can also email a nudge directly; copying the link always
works regardless.

When a milestone is newly earned, Vera says "Someone has a message for
you!" and plays any matching cheer full screen. A cheer attached to a
milestone that was already earned before it was recorded has missed that
moment, so it's queued instead and plays at the next app open ("You have a
message from Jake"), right after the proactive greeting.

A recorded cheer uploads straight to S3 when a bucket is configured (and
falls back to local disk if that upload fails, so a recording is never
lost over a flaky connection); `list_cheers`/`get_cheer` hand back a fresh
presigned `url` for an S3 cheer, or nothing for a local one, in which case
the frontend already knows to fall back to `/cheer-media/<file>`. This
matters beyond tidiness: a cloud-hosted MCP server's local disk doesn't
survive a redeploy or scale past one instance, so in that environment S3
is the only place a recording reliably lives.

## Media storage: local vs. S3

Local layout (always works, no AWS needed):

```
web/static/media/
  exercise/manifest.json + the video files it names
  meditations/manifest.json + the audio/video files it names
web/cheer_media/            (gitignored; cheers land here when S3 isn't configured)
```

S3 layout, once `VERA_S3_BUCKET` is set (optionally under `VERA_S3_PREFIX`):

```
<bucket>/<prefix>/media/exercise/<filename>       -- same filenames as the local manifest
<bucket>/<prefix>/media/meditations/<filename>
<bucket>/<prefix>/cheers/<generated-filename>.webm -- written automatically on upload
```

`vera/media.py` and `vera/family.py`'s `cheer_media_url` check the bucket first (a cached `HEAD` per filename) and fall back to the local path if the file isn't there, so you can upload routines to S3 one at a time without breaking the ones you haven't gotten to yet. To upload the exercise/meditation media once you have real recordings:

```powershell
aws s3 sync web/static/media s3://your-bucket-name/media
```

## AWS services used

| Service | Role in Vera |
|---|---|
| **Bedrock** (Amazon Nova Lite) | Powers the web simulator's conversational tool-use loop -- free-form chat, the proactive greeting, and deciding which MCP tool to call. On real Alexa+, this role is played by Alexa+'s own model; Vera's MCP tools don't change. |
| **Polly** | Text to speech for the web simulator's voice (neural engine, a slightly slower SSML rate for older ears), with disk caching. Alexa+ handles this natively in production. |
| **S3** | Optional storage for exercise/meditation videos and Family Cheers recordings, served back out via presigned URLs so the bucket can stay private. Required (not just nice to have) once the MCP server runs somewhere its local disk doesn't persist, like App Runner. |
| **App Runner** | Hosts the MCP server itself (`server.py`) with a public HTTPS endpoint, built straight from this GitHub repo -- see [Deploying to AWS App Runner](#deploying-the-mcp-server-to-aws-app-runner). |
| **SES** | Optional: lets the caregiver dashboard email a family member their cheer-recording nudge directly, instead of only copying the link. Sandbox mode by default (sender and every recipient must be verified). |

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
| `VERA_SES_FROM_EMAIL` | *(none)* | Verified sender for optional email nudges; without it, emailing a nudge fails (copying the record link still always works) |
| `VERA_S3_BUCKET` | *(none)* | Enables S3 storage for media/cheers; without it, everything falls back to local disk |
| `VERA_S3_PREFIX` | *(none)* | Optional key prefix inside the bucket |
| `AWS_REGION` | `us-east-1` | Region for S3 (and Bedrock/Polly/SES, in the web simulator) |

## Deploying the MCP server to AWS App Runner

The MCP server (`server.py`) is what Alexa+ -- or anything else speaking MCP -- actually talks to, so it's the piece that needs a public HTTPS endpoint. The web simulator stays local (or wherever you run it), pointed at that endpoint via `VERA_MCP_URL`.

This repo includes an `apprunner.yaml` so App Runner can build and run it with no Dockerfile:

```yaml
version: 1.0
runtime: python311
build:
  commands:
    build:
      - pip install -r requirements.txt
run:
  command: python server.py
  network:
    port: 8000
  env:
    - name: VERA_HOST
      value: "0.0.0.0"
```

Steps (AWS Console):

1. Push this repo to GitHub.
2. **App Runner > Create service > Source code repository**, connect your GitHub account, pick this repo and branch.
3. Deployment trigger: **Automatic** deploys a new version on every push to the branch.
4. Build settings: choose **Use a configuration file** (it'll find `apprunner.yaml`), or configure manually -- runtime Python 3, build command `pip install -r requirements.txt`, start command `python server.py`, port `8000`.
5. Add any environment variables you need beyond the ones in `apprunner.yaml`: `VERA_CORS_ORIGINS` (lock this down to your web simulator's origin instead of `*` once you have one), and, if you want S3-backed media/cheers, `VERA_S3_BUCKET` / `VERA_S3_PREFIX` / `AWS_REGION`.
6. If you're using S3, attach an instance role granting `s3:GetObject` and `s3:HeadObject` on that bucket -- that's all the deployed server needs, since it only ever reads (uploading cheer recordings happens from wherever the web simulator runs, not from App Runner).
7. Create the service. App Runner builds, deploys, and gives you a public `https://<random-id>.<region>.awsapprunner.com` URL -- the MCP endpoint is that URL plus `/mcp`.
8. Point anything that should talk to it (the web simulator, MCP Inspector) at `VERA_MCP_URL=https://<your-service>.awsapprunner.com/mcp`.

**Known limitation:** `data/vera.json` is a local JSON file, which is fine for a single always-on App Runner instance but won't survive a redeploy, and won't be shared if you scale past one instance. `vera/storage.py`'s `Store` class is a narrow, three-method interface (`get_user`/`save_user`/`list_users`/...) specifically so swapping it for DynamoDB later wouldn't touch any tool's logic -- just not done here, to keep this a one-file, zero-infrastructure demo.

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

Configuration (env vars): `VERA_MCP_URL` (default `http://127.0.0.1:8000/mcp`;
point this at your App Runner URL's `/mcp` once it's deployed),
`WEB_HOST` / `WEB_PORT` (default `127.0.0.1:8080`), `VERA_BEDROCK_MODEL_ID`
(default `us.amazon.nova-lite-v1:0`), `VERA_POLLY_VOICE` (default `Ruth`),
`VERA_POLLY_ENGINE` (default `neural`), `VERA_POLLY_RATE` (default `92%`),
plus everything under [Configuration](#configuration) (`AWS_REGION`,
`VERA_SES_FROM_EMAIL`, `VERA_S3_BUCKET`, `VERA_S3_PREFIX`). Needs AWS
credentials (e.g. via `aws configure`) with `bedrock:InvokeModel`,
`polly:SynthesizeSpeech`, `ses:SendEmail` for email nudges, and, if a
bucket is configured, `s3:PutObject` on it (this is where a recorded cheer
actually gets uploaded from).

## Friction log

Kept in [FRICTION_LOG.md](FRICTION_LOG.md), using the hackathon's own entry template (task attempted, steps taken, expected vs. actual, severity, workaround, suggestion) rather than prose here.

## Roadmap

- Optional check in calls
- Move `data/vera.json` to DynamoDB so the App Runner deployment survives a redeploy and can scale past one instance

## License

MIT
