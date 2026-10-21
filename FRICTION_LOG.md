# Friction Log

Fill one entry each time something slows you down. Submissions with friction logs can earn up to a 10% judging bonus, so log as you go rather than from memory at the end.

## Entry template

- **Task attempted:**
- **Steps taken:**
- **Expected:**
- **What actually happened:**
- **Severity:** (blocker / major / minor)
- **Workaround:**
- **Actionable suggestion:**

---

## Entries

### 1. Nova Lite leaking its own scratchpad into spoken replies
- **Task attempted:** Wiring Amazon Nova Lite's Converse API tool-use loop into the web simulator's chat/greeting layer (`web/bedrock_chat.py`), whose replies get spoken aloud and shown as a caption.
- **Steps taken:** Sent ordinary conversational prompts through the Converse API with tools attached and read back `output.message.content[0].text` as the reply to speak.
- **Expected:** Plain natural-language text in the reply, like the API's own docs examples show.
- **What actually happened:** Some replies arrived wrapped in `<thinking>...</thinking>` or `<response>...</response>` tags instead of plain text. Harmless in a text window, but reading `<thinking>I should check the user's streak...</thinking>` out loud would have been obviously broken.
- **Severity:** minor
- **Workaround:** Added `_clean_reply()` in `web/bedrock_chat.py`, which strips a `<thinking>` block and unwraps a `<response>` wrapper with two regexes before anything is spoken or shown.
- **Actionable suggestion:** Document, in the Converse API / Nova model card, that these wrapper tags are a known model behavior so builders know to sanitize before sending a reply to any surface (TTS, captions) that assumes plain text.

### 2. A 60+ call MCP test session started silently timing out at ~300s
- **Task attempted:** Adding Phase 6 (Family Cheers) tool calls to the existing end-to-end `tests/test_mcp_client.py`, which drove the whole test suite from one long-lived MCP client session.
- **Steps taken:** Appended the new tool calls to the existing single `test_full_flow` test (by then ~60 sequential `call_tool` calls in one `ClientSession` over Streamable HTTP) and ran the suite.
- **Expected:** A few more seconds added to what was already a fast test run.
- **What actually happened:** The whole suite started reliably timing out around the 300 second mark with a `ReadTimeout`/`ReadError` deep in `httpx`/`httpcore`, with no error for most of that time. First suspected the new tools themselves, then environment noise, before writing an isolated repro script that called just the new tools against a fresh server and confirmed they were fine individually.
- **Severity:** major (blocked the whole suite from running reliably, masking real failures)
- **Workaround:** Split the one giant test into three focused tests, each opening its own short-lived server + client session (`_server_session` async context manager). Full suite now runs in ~15 seconds, reliably, on the same machine.
- **Actionable suggestion:** For local Windows dev environments, keep MCP client test sessions short (a few dozen calls at most) and prefer several short-lived sessions over one long one -- this was the real fix, not a timeout tweak. *Correction, Phase 6:* splitting the test only raised the threshold, it didn't remove the actual bug -- see entry 8 for the real root cause and fix.

### 3. Vera talked over her own audio
- **Task attempted:** Playing a real meditation/exercise audio or video track right after Vera's spoken intro line on the same screen.
- **Steps taken:** Called `speakText(introLine)` and then immediately started `<audio>.play()`/`<video>.play()` for the real track.
- **Expected:** The intro finishes, then the track starts.
- **What actually happened:** Both are asynchronous, so without awaiting the intro's completion callback first, the real track started immediately and overlapped the spoken intro for its first several seconds -- easy to miss in review since it only shows up with real audio playing, not in a quiet unit test.
- **Severity:** minor
- **Workaround:** Made the track-start code `await` the intro's `onEnd` callback before calling `.play()`, and added a "listen or repeat along" spoken prompt once the track actually starts.
- **Actionable suggestion:** n/a (own code, not an AWS service issue).

### 4. Deciding what a "family member" needs to not be an account
- **Task attempted:** Designing Family Cheers (Phase 6) under a hard constraint from the project brief: no logins anywhere, for anyone, including family members who aren't the primary user.
- **Steps taken:** Considered a few options (a lightweight shared household password, a magic-link email flow, a one-time code) before settling on a single unguessable per-family-member URL (`secrets.token_urlsafe`) as the entire access model for their record/cheer page.
- **Expected:** This felt like it should need more ceremony -- most consumer apps reach for an account as the default unit of access, even for a single-purpose page.
- **What actually happened:** A single private link turned out to be both simpler to build and more appropriate for a person who should be able to do exactly one thing (record a cheer) from their phone, once or many times, with nothing to remember or sign into. Took longer to be comfortable with than it should have, purely because it's unfamiliar compared to defaulting to accounts.
- **Severity:** minor
- **Workaround:** n/a -- this was a design decision, not a bug.
- **Actionable suggestion:** n/a.

### 5. `lru_cache` and mocked AWS state don't mix cleanly in tests
- **Task attempted:** Caching whether a given S3 object exists (`vera/cloud_storage.object_exists`) so `list_sessions` doesn't issue a `HEAD` request to S3 on every single call.
- **Steps taken:** Wrapped `object_exists` in `functools.lru_cache` and wrote tests that monkeypatch the S3 client/bucket to exercise both "file is in the bucket" and "file isn't in the bucket" branches.
- **Expected:** Each test's monkeypatched state would be isolated.
- **What actually happened:** `lru_cache` lives on the function object itself, which is process-wide and ignores whatever a given test monkeypatched -- a cached `True`/`False` for a given filename quietly leaked from one test into the next test that happened to check the same filename under different (mocked) bucket state.
- **Severity:** minor
- **Workaround:** Each test that exercises `object_exists` now explicitly calls `object_exists.cache_clear()` before and after, rather than relying on monkeypatch's automatic teardown.
- **Actionable suggestion:** n/a (own code, not an AWS service issue).

### 6. A presigned-URL call with no bucket configured crashed instead of degrading
- **Task attempted:** Making every public function in `vera/cloud_storage.py` safe to call even when `VERA_S3_BUCKET` isn't set (the default for a laptop demo), so callers don't each need their own guard.
- **Steps taken:** Wrote `except (ClientError, BotoCoreError)` around the `boto3` calls in `presigned_url`/`object_exists`, on the assumption that an S3 call with a missing/invalid bucket would raise one of those.
- **Expected:** A clean `None`/`False` return when S3 isn't configured, same as the module's own docstring promised ("entirely optional... every function here is a no-op").
- **What actually happened:** `boto3.generate_presigned_url(Bucket=None, ...)` doesn't raise a `ClientError` at all -- it blows up with a raw `TypeError` from deep inside botocore's internal bucket-name validator, before any network call, which my `except` clause didn't catch.
- **Severity:** major (would have crashed any MCP tool call that touched an S3-flagged cheer the moment the bucket env var was unset or misconfigured)
- **Workaround:** Added an explicit `if not enabled(): return None/False` guard at the top of every public function in the module, instead of relying on exception handling alone.
- **Actionable suggestion:** For `boto3`/`botocore`, a missing required parameter like `Bucket` could reasonably raise a documented `ParamValidationError` (which it does, in general) consistently surfaced as a catchable, typed exception everywhere -- in this case it surfaced as a bare `TypeError` from an internal validator function instead, which is easy to miss when scoping an `except` clause to the documented exception types.

### 7. Vera's own circle was cropping her head and feet
- **Task attempted:** Reviewing the Vera companion's layout per the cleanup brief ("Vera's full body must show in her circle, no cropped head").
- **Steps taken:** Inspected `.vera-figure img` in `web/static/css/style.css`, which set the character image to `width: 112%; height: 112%` inside a circular, `overflow: hidden` frame.
- **Expected:** That rule looked intentional (oversizing slightly to avoid letterboxing gaps in the circle's corners), so initially assumed the "cropped head" issue was somewhere else -- maybe the image assets themselves, or a different companion state.
- **What actually happened:** The source art (`web/static/img/vera-*.webp`) is a square image with the character drawn close to the top/bottom edges and more generous side margins. At exactly 100% scale, a square image exactly fills a circular frame of the same size without clipping the character (only the image's empty corner whitespace gets masked by the circle). The extra 12% scale pushed the character's ear-tops and feet past the circle's boundary, clipping exactly the "cropped head" the brief described.
- **Severity:** minor
- **Workaround:** Changed `.vera-figure img` to `width: 100%; height: 100%` (object-fit: contain unchanged). Verified visually at desktop, tablet, and phone widths.
- **Actionable suggestion:** n/a (own code).

### 8. The real root cause of entry 2's "timeout": an unread subprocess pipe, not call volume
- **Task attempted:** Adding `test_family_cheers_flow`'s new, larger Family Cheers assertions (Phase 6 rebuild: ~25 tool calls in one test) and running the suite.
- **Steps taken:** The test reliably printed its pass/fail result character, then hung -- sometimes for over three minutes -- before pytest could print anything further. Wrote a standalone script replaying the identical call sequence against a manually-started server (logging to a file, not a pipe) -- it completed correctly and quickly, every time, which ruled out the new tool logic itself. The one real difference: `tests/test_mcp_client.py`'s `_server_session` helper starts the server with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT` and never reads `proc.stdout`.
- **Expected:** Entry 2's fix (shorter, focused tests) should have kept every test well under whatever limit caused the original ~300s timeout.
- **What actually happened:** An OS pipe has a small, fixed buffer (commonly 64KB). Uvicorn logs roughly one line per HTTP request; with nobody draining `proc.stdout`, enough log lines eventually fill that buffer, and the next write from the server process blocks -- the server itself hangs mid-request, the client's request hangs waiting for a response, and eventually times out or (worse) the whole thing hangs past any client-side timeout during the next cleanup step. Entry 2's "split into three tests" fix just kept each test's call count below the threshold where this tipped over; this test's ~25 calls (plus whatever the FastMCP/uvicorn stack logs per request now) was enough to cross it again. This is a textbook `subprocess.PIPE` deadlock, not test-call-volume flakiness.
- **Severity:** major (the same underlying bug as entry 2, now understood precisely, and confirmed to resurface as the test suite grows)
- **Workaround:** Changed `_server_session` to `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` (the tests never need the server's console output) and made the teardown kill the process outright if a graceful `terminate()` doesn't exit within 5 seconds. Reran the full suite and the previously-hanging test five times in a row with no hang.
- **Actionable suggestion:** Whenever a test harness captures a child process's stdout/stderr with `PIPE`, something must actually read it (or redirect to `DEVNULL`/a file) -- otherwise the buffer-fill deadlock is a when, not an if, as the process's own logging grows over the life of a project.
