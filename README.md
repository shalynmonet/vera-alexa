# Vera

A warm wellness companion for older adults, built for Alexa+. Vera keeps minds and bodies busy with four games, guided exercise routines, and guided meditation, and celebrates progress with a visual fitness log of streaks and milestones. Family members can leave her short audio/video cheers to play at just the right moment, and caregivers get a simple daily summary.

Vera is named after my late great-grandmother and inspired by caring for my grandmother -- specifically, by how much of caregiving is just noticing: did she move today, did she eat, is she lonely, is anyone keeping track. I built Vera to be the thing quietly keeping track, so a family doesn't have to ask about it every day, and so the person at the center of it all gets encouragement instead of a checklist.

**On Alexa+, Vera uses the customer's Amazon account identity automatically** -- there are no accounts, logins, or passwords anywhere in this app. On a real Echo, Vera opens as the signed-in household member automatically, and Alexa voice profiles tell household members apart. The simulator mirrors this by remembering the person on each device. A family member's cheer-recording link works from a single private, unguessable URL, nothing to sign into either.

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
| `log_activity` | Logs a self-reported activity with no guided session -- a walk, bike or stationary bike ride, gardening, dancing, swimming, or anything else by name -- toward the same streak, goal, and milestones. Refuses to log stated intent as completed -- see "Only log what's actually done" below |
| `plan_activity`, `get_planned_activities` | Remembers an activity the person said they intend to do but haven't yet ("I'll walk later") so the next greeting can naturally ask how it went, instead of logging a guess now |
| `get_fitness_log` | Calendar grid (both a flat list and 5 Sunday-Saturday weeks), totals, streak, weekly goal, and badges deduplicated with a count (e.g. "Weekly Goal Met ×3") |
| `get_day_detail` | Everything that happened on one day -- activities, game scores, cheers played, badges earned -- for tapping a square on the Progress calendar |
| `get_streak` | Current and longest streak |
| `check_milestones` | Awards any newly earned badges |
| `get_daily_summary` | Caregiver friendly summary of the day, including self-reported activities |
| `remember_fact` | Saves a meaningful personal detail (family, hobbies, upcoming events) to bring up again later; refuses health details |
| `get_memories` | Recent personal facts, most recent first, for Nova to naturally bring one up in conversation |
| `get_engagement_trends` | Gentle, descriptive accuracy/pace trends per cognitive game, month over month -- never a score, an alert, or a health claim |
| `list_family`, `add_family_member`, `update_family_member`, `remove_family_member` | Family members who can record cheers (just a name and phone to add; relationship/nickname/email are the family member's own answers from their first visit) |
| `resolve_family_token` | Looks up who a private record-page link belongs to and who it's for, and whether they've finished first-visit setup |
| `upcoming_milestones` | Milestones the person is one step away from, each with a ready-made "almost there" nudge |
| `get_cheer_prompts` | Ready-made cheer scripts generated from the person's real data -- one per close milestone, three fixed "anytime" lines, one per activity they actually do |
| `add_cheer`, `list_cheers`, `next_cheer`, `mark_cheer_played`, `delete_cheer` | Save, browse, and play back family cheers -- each is locked until its milestone/activity condition is met, then surfaces through `next_cheer`'s daily cap and family-member rotation |
| `check_family_alerts`, `mark_alert_sent` | "Running low" email nudges when a family member's unlocked-cheer queue drops to 1 or 0, sent once per drop |
| `handoff_session_to_display`, `get_display_session` | Hands the active exercise/meditation/progress session to a simulated display (the Living Room TV), or brings it back to the main screen |

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

### Chat with Vera

A dedicated Chat screen for a free-form conversation, reusing the exact same Nova chat loop as every other screen's mic/type input -- both sides of the conversation show as large captions, and five tappable starter chips sit above the mic:

> "Tell me a story" &middot; "Let's talk about the old days" &middot; "Tell me something that will make me smile" &middot; "What should we do next?" &middot; "Tell me a fun fact from history"

Up to two of the five chips personalize from `get_memories` (e.g. a remembered family event or hobby); the chip-selection logic is a small, dependency-free module (`web/static/js/chat-chips.js`) so it can be unit tested directly under Node (`tests/test_chat_chips.py`) rather than only by hand in a browser. Tapping a used chip swaps it for a fresh one -- another memory first, then a default -- so the row doesn't go stale; the chips hide while Vera's reply is in flight and reappear once she's done.

"Let's talk about the old days" leads Nova into asking one gentle reminiscence question at a time (first job, hometown, a favorite song, how she met someone), saving anything meaningful with `remember_fact`. "What should we do next?" has Nova check `get_fitness_log`, `get_streak`, and `get_planned_activities` and suggest one specific thing, falling back to friendly discovery questions (a hobby, something around the house) once everything available has already been done for the day.

Because this screen invites open-ended conversation rather than a fixed set of commands, the system prompt carries a few firm boundaries that override everything else, including the usual short-reply style: never medical advice, a diagnosis, or medication guidance (suggest her doctor or family instead); a mentioned fall, chest pain, trouble breathing, or urgent need for help gets an immediate, verbatim "Please call 911 or use your emergency button right now" *before* any sympathy -- Nova Lite needed that exact required sentence, not just a general instruction to take it seriously, to say it reliably; sadness or loneliness gets real warmth and an offer to help her feel connected to family (replaying a cheer, calling someone); and Vera never asks for money, bank/card details, a password, or a Social Security number, and warns that a caller or message asking for them may be a scam. See `tests/test_bedrock_chat.py` for the guardrail prompt tests.

### Exercise and meditation media

Real videos and audio are described by a hand-edited `manifest.json` next to each category (title, minutes, file, thumbnail, and for exercise, narration steps). `vera/media.py` resolves each manifest entry's file to a playable URL -- from the S3 bucket if one's configured and the file has been uploaded there, otherwise from local disk -- and reports the routine as `available` only once the file actually exists somewhere, so a routine with no recording yet simply shows a friendly "coming soon" card. No code change is needed either way: drop the file in locally, or upload it to the bucket, with the exact filename the manifest expects. The four exercise routines (chair stretch, seated strength, balance, gentle walking) ship as narration-only placeholders today; meditations are built from whatever real files already exist (currently one: "Healing Affirmations"). See [Media storage](#media-storage-local-vs-s3) below for the folder/bucket layout.

### Logging any activity, three ways

Beyond the guided sessions, three ways to log an unguided activity (walk, bike, stationary bike, gardening, dancing, swimming, or anything else by name) all land on the same `log_activity` tool:

1. **Voice, through Nova** -- "I walked for 20 minutes" or "I did half an hour of gardening."
2. **Log an Activity button** (on the Exercise screen) -- pick the activity, then minutes (5 to 60), then an optional feeling.
3. **Start a Walk / Start a Ride** (also on Exercise) -- a live stopwatch; Vera checks in every few minutes, and tapping "I'm Done" logs the elapsed time automatically.

Every tool accepts an optional `on_date` (YYYY-MM-DD) so demos and tests can use a fixed date.

### Only log what's actually done

Saying "I'm going to walk today, that sounds good" must never get logged as
a finished walk -- stated intent isn't a completed activity. `log_activity`
and `log_completion` take two extra parameters, `completed` and
`user_statement`, meant for Nova's conversational path only (UI buttons and
a session's own "ended"/"I'm done" event don't need either to be
meaningful, since the tap or the event itself already *is* the completion
signal). When Nova calls either tool from a chat message, it passes the
person's exact words and whether they said they'd actually finished;
`server._completion_guard_error` refuses the call -- with a message telling
Nova what to do instead -- when `completed` is false, the statement reads
as a future plan ("will", "going to", "later", "sounds good") without a
clear completion alongside it, or the minutes are zero/missing (so Nova
can't log a made-up duration -- it has to ask). The system prompt tells
Nova to respond to a refusal by asking a clarifying question, encouraging
warmly, or calling `plan_activity` -- never by retrying the same call.

`plan_activity` remembers a stated intent ("I'll ride my bike later")
without logging anything; `get_planned_activities` feeds it back to the
next proactive greeting ("Did you get your bike ride in today?") so Vera
follows up naturally instead of letting it vanish. A plan is cleared the
moment the matching activity is actually logged, and quietly expires at
the end of the day either way -- a skipped plan is never raised as
something missed.

`check_activity_phrases.py` sends the phrases from this fix's bug report
through the real Nova chat loop and reports what happened (logged,
refused, planned, or asked) -- a living check against regressions.

### Family Cheers

Family members can record a short audio, "voice + photo", or video cheer
for the person using Vera, with no account or login of their own -- the
caregiver adds just a name and phone number (`/caregiver/<user_id>`,
linked from the Progress screen), and each family member gets one
permanent, private, unguessable link (`/cheer/<token>`, `vera/family.py`).
Adding them shows a **Text Invite** button (an `sms:` link prefilled with
an invite message, opening the phone's own Messages app -- zero server
involvement) and a Copy Link fallback.

**A family member's first visit** is a short welcome screen -- confirm
their name, pick a relationship, say what they call the person (prefilled
if the caregiver guessed one), and optionally leave an email with an
"email me when they're close to a milestone or running low on my cheers"
checkbox (`update_family_member`). Every later visit skips straight to
recording, with a small "Edit my details" link.

**The family link page** ("Help Mom keep going 💜") shows a 5-cheer goal
with progress ("2 of 5 sent") and ready-made scripts generated from the
person's *real* data (`get_cheer_prompts`): one per milestone they're
close to ("Congrats on your 7 day streak!"), three fixed "anytime" lines,
and one per activity they actually do ("Enjoy your meditation, Mom").
Tapping a script opens the recorder with it shown; "Record My Own
Message" opens the same recorder with a choice of when it should play
(anytime, a specific upcoming milestone, or after a specific activity).
Recording (`web/static/js/cheer-record.js`) is capped at 15 seconds with a
visible countdown, auto-stops, and offers preview/re-record before Send;
the server independently re-validates that same 15 second cap and a size
limit before accepting the upload.

**Locked until it matters:** a cheer starts `locked` unless its condition
is already true, and `add_cheer`/the activity-logging path (`_unlock_cheers`
in server.py) unlocks it the moment that becomes true -- a milestone cheer
when that milestone is earned, an activity cheer the next time that
activity type is logged, an "anytime" cheer on the person's very next
completed activity after it was recorded. `next_cheer` picks the next
`unlocked` one (oldest first), capped at `VERA_MAX_CHEERS_PER_DAY` (default
2) per day and rotating across family members so one person's cheers never
play back to back. The same `next_cheer` call drives every delivery
moment: a newly earned milestone ("Someone has a message for you!"), a
workout's step-break pause (one at most, full screen, "voice + photo"
cheers showing the photo while the audio plays), and app open ("You have a
message from Jake"). Home's **Cheers** card shows a count of what's
waiting (new and still locked) without revealing anything; tapping it
opens its own screen with every `unlocked` cheer, any `played` one
available to replay, and a locked count ("2 surprises from family
waiting"). Either the person or the caregiver can `delete_cheer` any cheer
at any time.

**Alerts:** `check_family_alerts` finds any family member whose unlocked
queue just dropped to 1 or 0 (opted into email) and the caregiver
dashboard sends one email nudge the next time it loads -- `mark_alert_sent`
keeps it from repeating until the count changes again. This app has no
background job runner, so "next dashboard load" is the honest trigger
point rather than a true scheduled check.

A recorded cheer (and its optional photo) uploads straight to S3 when a
bucket is configured, falling back to local disk if that upload fails so a
recording is never lost over a flaky connection; `list_cheers`/`next_cheer`
hand back a fresh presigned `url`/`photo_url` for an S3 cheer, or nothing
for a local one, in which case the frontend already knows to fall back to
`/cheer-media/<file>`. This matters beyond tidiness: a cloud-hosted MCP
server's local disk doesn't survive a redeploy or scale past one instance,
so in that environment S3 is the only place a recording reliably lives.

Automatic SMS nudges (the invite itself is always just a plain `sms:`
link, no AWS involved) are built on AWS End User Messaging SMS behind
`VERA_SMS_ENABLED` (off by default, since it needs a registered toll-free
number -- see Configuration) and always append "Reply STOP to opt out."

### Simulated living room display

**`/tv/<user_id>` is a SIMULATED Fire TV display, not a real device
integration** -- said plainly in its own footer, since nothing here talks
to an actual Fire TV. Saying "put this on the TV" (or "let's do chair yoga
in the living room") while an exercise, meditation, or progress session is
open calls `handoff_session_to_display`, which stores a small snapshot of
what's currently playing; the same "📺 Send to Living Room" button does
the same thing directly, for testing without voice. The main screen keeps
actually driving the session -- timers, narration, milestone/cheer checks
are all unchanged -- it just swaps its detailed view for a "Now playing on
Living Room TV" banner with a "Bring it back" button. The `/tv` page
subscribes over server-sent events (`/api/display/events/<user_id>`) and
mirrors that snapshot close to instantly, including a cheer that comes due
mid-workout, which plays full screen there instead of on the main screen
("voice + photo" cheers show the photo while the audio plays). Bringing it
back (either button) clears the handoff and the TV returns to its idle
"waiting for a session" state.

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
| **S3** | Optional storage for exercise/meditation videos and Family Cheers recordings, served back out via presigned URLs so the bucket can stay private. Required (not just nice to have) once the MCP server runs somewhere its local disk doesn't persist -- see Deployment below. |
| **SES** | Optional: lets the caregiver dashboard email a family member their cheer-recording nudge directly, instead of only copying the link. Sandbox mode by default (sender and every recipient must be verified). |
| **End User Messaging SMS** | Optional, off by default (`VERA_SMS_ENABLED`): automatic SMS nudges once a toll-free number is registered. The family invite itself never needs this -- it's a plain `sms:` link the caregiver's own phone sends. |

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
| `VERA_MAX_CHEERS_PER_DAY` | `2` | How many family cheers `next_cheer` will surface in one day |
| `VERA_SMS_ENABLED` | `false` | Turns on automatic SMS nudges (not the family invite, which is always a plain `sms:` link) |
| `VERA_SMS_ORIGINATION_NUMBER` | *(none)* | Your registered toll-free number; required once `VERA_SMS_ENABLED=true` |
| `AWS_REGION` | `us-east-1` | Region for S3/SMS (and Bedrock/Polly/SES, in the web simulator) |

## Deployment

For this submission, the MCP server (`server.py`) runs locally, the same `python server.py` from Run it above, alongside the web simulator on the same machine. AWS App Runner was the original plan for giving it a public HTTPS endpoint, but App Runner is currently closed to new customers, so that path isn't available right now.

**Planned deployment path: Amazon ECS Express Mode.** Once available, this would containerize `server.py` (a small Dockerfile around the existing `pip install -r requirements.txt` + `python server.py`) and deploy it to ECS using Express Mode's simplified setup -- a public HTTPS endpoint without hand-writing a task definition or provisioning a cluster/VPC from scratch. The same `VERA_HOST=0.0.0.0` and `VERA_PORT` env vars would carry over unchanged; `VERA_MCP_URL` on the web simulator would just point at whatever endpoint ECS Express Mode hands back.

**Known limitation either way:** `data/vera.json` is a local JSON file, which is fine for a single always-on instance but won't survive a redeploy, and won't be shared if you scale past one instance. `vera/storage.py`'s `Store` class is a narrow, three-method interface (`get_user`/`save_user`/`list_users`/...) specifically so swapping it for DynamoDB later wouldn't touch any tool's logic -- just not done here, to keep this a one-file, zero-infrastructure demo.

## Web simulator

An Echo Show style Alexa+ simulator in the browser: big text, high contrast,
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
home has six sections -- Games, Exercise, Meditations, Progress, Cheers, Chat --
each backed by its own MCP tool(s) so new games or routines show up
automatically. Every screen but Home has a clearly labeled "← Back" button
to its parent screen (Home's own tiles are the entry points, so it needs
none), alongside the Home button.

Vera herself is a persistent on-screen companion (a purple elephant) built
from `web/static/js/companion.js`: large and centered on the start/home
screens with a speech bubble for her words, a small corner companion on
activity screens, shrinking and dimming during a video or meditation
session, and animating to center stage to celebrate a new milestone. Each
section has its own idle pose (thinking for Games, exercising for Exercise,
meditating for Meditations, celebrating for Progress), with a gentle idle
bob and talk/celebrate bounce that respects `prefers-reduced-motion`. Poses
are plain images today; the module is structured so any pose can later
become a looping video without touching call sites. Each pose's image is
background-removed with [rembg](https://github.com/danielgatis/rembg) so
Vera sits directly on whatever screen is behind her (including the `/tv`
display) instead of inside a white box; the originals are kept in
`web/static/img/originals/`.

```powershell
# with the Vera MCP server already running (see above)
pip install -r requirements.txt
python -m web.app   # http://127.0.0.1:8080
```

Configuration (env vars): `VERA_MCP_URL` (default `http://127.0.0.1:8000/mcp`;
point this at wherever the MCP server ends up deployed, once it is),
`WEB_HOST` / `WEB_PORT` (default `127.0.0.1:8080`), `VERA_BEDROCK_MODEL_ID`
(default `us.amazon.nova-lite-v1:0`), `VERA_POLLY_VOICE` (default `Ruth`),
`VERA_POLLY_ENGINE` (default `neural`), `VERA_POLLY_RATE` (default `92%`),
plus everything under [Configuration](#configuration) (`AWS_REGION`,
`VERA_SES_FROM_EMAIL`, `VERA_S3_BUCKET`, `VERA_S3_PREFIX`,
`VERA_MAX_CHEERS_PER_DAY`, `VERA_SMS_ENABLED`, `VERA_SMS_ORIGINATION_NUMBER`).
Needs AWS credentials (e.g. via `aws configure`) with `bedrock:InvokeModel`,
`polly:SynthesizeSpeech`, `ses:SendEmail` for email nudges, `s3:PutObject`
on the bucket if one's configured (this is where a recorded cheer and its
optional photo actually get uploaded from), and, only once
`VERA_SMS_ENABLED=true`, `sms-voice:SendTextMessage`.

## Friction log

Kept in [FRICTION_LOG.md](FRICTION_LOG.md), using the hackathon's own entry template (task attempted, steps taken, expected vs. actual, severity, workaround, suggestion) rather than prose here.

## Roadmap

- A native Fire TV app for the Living Room Display, instead of today's simulated `/tv` page
- Ring integration for gentle, activity-aware check-ins -- only with the resident's consent, and never framed as surveillance
- Voice-based cognitive screening, developed together with clinicians rather than inferred from game scores alone
- Automatic SMS nudges once a toll-free number is registered (the code already exists behind `VERA_SMS_ENABLED`; see Family Cheers)
- Deploy the MCP server via Amazon ECS Express Mode (App Runner's replacement here, since it's closed to new customers) for a public HTTPS endpoint
- Move `data/vera.json` to DynamoDB so that deployment survives a redeploy and can scale past one instance

## License

MIT
