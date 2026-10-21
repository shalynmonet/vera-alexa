import { callTool, chat, greet } from "./api.js";
import { listen, speechRecognitionSupported } from "./speech.js";
import { speakText, stopSpeaking, pauseSpeaking, resumeSpeaking } from "./voice.js";
import { Companion } from "./companion.js";

const SCREENS = ["start", "home", "games", "memory", "matching", "saying", "category", "exercise", "stretch", "meditation", "progress", "log-activity", "timed-activity", "cheers"];
const PARENT_SCREEN = {
  games: "home", memory: "games", matching: "games", saying: "games", category: "games",
  exercise: "home", stretch: "exercise", "log-activity": "exercise", "timed-activity": "exercise",
  meditation: "home", progress: "home", cheers: "home",
};
const GAME_ICONS = { memory_game: "🧠", matching_game: "🃏", saying_game: "📜", category_game: "🗂️" };
const ENCOURAGEMENTS = [
  "You're doing wonderfully. Keep it up!",
  "Nice and steady, just how we like it.",
  "I'm so glad we're doing this together.",
  "Keep going at your own pace.",
  "You're doing great today.",
];
const MAX_HISTORY = 20;
const REMEMBERED_USER_KEY = "vera_user_id";
let conversationHistory = [];
let greetedThisSession = false; // proactive greeting fires once per app open/profile
let currentUserId = null;

const el = (id) => document.getElementById(id);

// Remembering the chosen profile is a per-viewer convenience (skip the
// picker next visit on this device), not a source of truth -- the server
// still owns the real profile data, so a blocked/cleared store just means
// falling back to the picker.
function getRememberedUserId() {
  try {
    return localStorage.getItem(REMEMBERED_USER_KEY);
  } catch {
    return null;
  }
}

function rememberUserId(userId) {
  try {
    localStorage.setItem(REMEMBERED_USER_KEY, userId);
  } catch {
    // Storage unavailable (private browsing, blocked, etc) -- the picker
    // will just show again next visit, which is a fine fallback.
  }
}

// ---------- shared chrome: screen router, companion speech, celebrations ----------

let current = "start";
let activeTimers = [];     // interval/timeout ids to clear on screen change
let micListening = false;

function trackTimer(id) {
  activeTimers.push(id);
  return id;
}

function clearActiveTimers() {
  activeTimers.forEach((id) => {
    clearInterval(id);
    clearTimeout(id);
  });
  activeTimers = [];
}

function showScreen(name) {
  const leaving = current;
  clearActiveTimers();
  Companion.setVideoMode(false);
  if (leaving === "meditation" && name !== "meditation") stopMeditationEarly();
  if (leaving === "stretch" && name !== "stretch") {
    const video = el("stretch-video").querySelector("video");
    if (video) video.pause();
  }
  SCREENS.forEach((s) => el(`screen-${s}`).classList.toggle("hidden", s !== name));
  current = name;
  Companion.placeInScreen(name);
  el("back-btn").classList.toggle("hidden", !PARENT_SCREEN[name]);
  if (name === "start") renderStart();
  if (name === "home") renderHome();
  if (name === "games") renderGamesList();
  if (name === "exercise") renderExerciseList();
  if (name === "meditation") {
    renderMeditationList();
    el("meditation-session").classList.add("hidden");
  }
  if (name === "progress") renderProgress();
  if (name === "log-activity") resetLogActivity();
  if (name === "cheers") renderCheersScreen();
}

function goBack() {
  const parent = PARENT_SCREEN[current];
  if (parent) showScreen(parent);
}

async function say(text) {
  if (!text) return;
  const mic = el("mic-btn");
  await Companion.say(text, (callbacks) => speakText(text, {
    ...callbacks,
    onStart: () => mic.classList.add("speaking"),
    onEnd: () => mic.classList.remove("speaking"),
  }));
}

async function celebrate(milestones) {
  if (!milestones || !milestones.length) return;
  const overlay = el("celebration");
  const titleEl = el("celebrate-title");
  const mic = el("mic-btn");
  overlay.classList.remove("hidden");
  for (const m of milestones) {
    titleEl.textContent = m.title;
    const line = m.celebration || `Congratulations, you earned ${m.title}!`;
    await Companion.celebrate(line, (callbacks) => speakText(line, {
      ...callbacks,
      onStart: () => mic.classList.add("speaking"),
      onEnd: () => mic.classList.remove("speaking"),
    }));
    await sleep(800);
  }
  overlay.classList.add("hidden");
  titleEl.textContent = "";

  // At most one cheer per celebration moment -- next_cheer already applies
  // the daily cap and rotates across family members.
  await tryPlayNextCheer();
}

// ---------- family cheers ----------

function showCheerOverlay(cheer) {
  return new Promise((resolve) => {
    const overlay = el("cheer-overlay");
    const videoEl = el("cheer-video");
    const audioEl = el("cheer-audio");
    const photoEl = el("cheer-photo");
    const isVideo = cheer.media_type === "video";
    const hasPhoto = cheer.media_type === "voice_photo" && (cheer.photo_url || cheer.photo_file);
    el("cheer-from").textContent = `A message from ${cheer.family_name}`;
    videoEl.classList.toggle("hidden", !isVideo);
    audioEl.classList.toggle("hidden", isVideo);
    photoEl.classList.toggle("hidden", !hasPhoto);
    if (hasPhoto) photoEl.src = cheer.photo_url || `/cheer-media/${cheer.photo_file}`;
    const mediaEl = isVideo ? videoEl : audioEl;
    mediaEl.src = cheer.url || `/cheer-media/${cheer.file}`;
    overlay.classList.remove("hidden");
    mediaEl.play().catch(() => {});

    const finish = () => {
      videoEl.pause();
      audioEl.pause();
      videoEl.removeAttribute("src");
      audioEl.removeAttribute("src");
      photoEl.removeAttribute("src");
      overlay.classList.add("hidden");
      el("cheer-dismiss-btn").removeEventListener("click", finish);
      mediaEl.removeEventListener("ended", finish);
      resolve();
    };
    el("cheer-dismiss-btn").addEventListener("click", finish);
    mediaEl.addEventListener("ended", finish, { once: true });
  });
}

// The single place any screen asks "is a family cheer due right now?" --
// server-side next_cheer already applies the daily cap and rotates across
// family members, so every call site (a milestone, a workout step break,
// app open) just needs to ask and play whatever comes back, or nothing.
async function tryPlayNextCheer({ onAppOpen = false } = {}) {
  let cheer;
  try {
    cheer = (await callTool("next_cheer", { user_id: currentUserId })).cheer;
  } catch {
    return false;
  }
  if (!cheer) return false;

  if (displayActive) {
    // The session is on the Living Room TV -- the cheer shows there
    // instead of on the main screen (see web/static/js/tv.js).
    await pushDisplaySnapshot({ ...lastDisplaySnapshot, cheer });
    await sleep(6000);
    await pushDisplaySnapshot({ ...lastDisplaySnapshot, cheer: null });
  } else {
    await say(onAppOpen ? `You have a message from ${cheer.family_name}.` : "Someone has a message for you!");
    await showCheerOverlay(cheer);
  }
  try {
    await callTool("mark_cheer_played", { cheer_id: cheer.id, user_id: currentUserId });
  } catch {
    // not fatal -- worst case it's offered again next time
  }
  return true;
}

// ---------- simulated living room display ----------
// A SIMULATED Fire TV (see web/static/tv/display.html) -- handing a
// session off to it just means mirroring a small snapshot of what's
// currently playing through handoff_session_to_display, which the TV page
// picks up over server-sent events (web/static/js/tv.js). The main screen
// keeps actually driving the session (timers, narration, cheer checks);
// it just hides its own detailed UI in favor of a small banner while a
// session is handed off.

let displayActive = false;
let lastDisplaySnapshot = null;

async function pushDisplaySnapshot(session) {
  lastDisplaySnapshot = session;
  try {
    await callTool("handoff_session_to_display", { user_id: currentUserId, display: "tv", session });
  } catch {
    // best-effort -- the main screen still works fine on its own
  }
}

function sendToDisplay(initialSession, bannerId, detailId) {
  displayActive = true;
  el(bannerId).classList.remove("hidden");
  el(detailId).classList.add("hidden");
  pushDisplaySnapshot(initialSession);
}

function bringBackFromDisplay(bannerId, detailId) {
  displayActive = false;
  lastDisplaySnapshot = null;
  el(bannerId).classList.add("hidden");
  el(detailId).classList.remove("hidden");
  callTool("handoff_session_to_display", { user_id: currentUserId, session: null }).catch(() => {});
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function sleep(ms) {
  return new Promise((resolve) => trackTimer(setTimeout(resolve, ms)));
}

function greetingWord() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function tickClock() {
  el("clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ---------- profiles (start screen) ----------

async function renderStart() {
  const list = el("profile-list");
  list.innerHTML = `<div class="say-text">Loading…</div>`;
  let profiles;
  try {
    const res = await callTool("list_profiles", {});
    profiles = res.profiles;
  } catch {
    list.innerHTML = `<div class="say-text">Couldn't reach Vera's server. Is it running?</div>`;
    return;
  }
  list.innerHTML = profiles.map((p) => `
    <button class="tile profile-tile" data-user-id="${escapeHtml(p.user_id)}">
      <span class="tile-icon">👤</span>
      <span class="tile-label">Continue as ${escapeHtml(p.name)}</span>
    </button>
  `).join("");
  list.querySelectorAll(".profile-tile").forEach((btn) => {
    btn.addEventListener("click", () => selectProfile(btn.dataset.userId));
  });
  await say("Hi there! Who's joining me today?");
}

function selectProfile(userId) {
  currentUserId = userId;
  conversationHistory = [];
  greetedThisSession = false;
  rememberUserId(userId);
  showScreen("home");
}

// ---------- context-aware input: who gets the next thing the user says ----------

let pendingAnswer = null; // function(text) | null
let skipStretchStep = null; // function() | null — resolves the current stretch step early

async function routeUtterance(text) {
  if (!text) return;
  if (pendingAnswer) {
    const handler = pendingAnswer;
    pendingAnswer = null;
    handler(text);
    return;
  }

  try {
    const result = await chat(text, conversationHistory, currentUserId);
    conversationHistory = (result.history || conversationHistory).slice(-MAX_HISTORY);
    if (result.reply) await say(result.reply);
    await handleBedrockToolCalls(result.tool_calls || []);
    return;
  } catch {
    // Bedrock chat isn't configured, or the request failed (network, AWS
    // permissions, etc). Fall back to simple keyword routing so the demo
    // still works without it.
  }

  const intent = parseIntent(text);
  if (intent === "home") { showScreen("home"); return; }
  if (intent === "memory") { showScreen("memory"); startMemoryGame(); return; }
  if (intent === "matching") { showScreen("matching"); startMatchingGame(); return; }
  if (intent === "saying") { showScreen("saying"); startSayingGame(); return; }
  if (intent === "category") { showScreen("category"); startCategoryGame(); return; }
  if (intent === "stretch") { showScreen("stretch"); startStretch(); return; }
  if (intent === "meditation") { showScreen("meditation"); return; }
  if (intent === "progress") { showScreen("progress"); return; }
  await say(`I heard "${text}". Try saying memory game, matching pairs, finish the saying, word categories, chair stretch, meditation, or my progress.`);
}

// Dispatch tool calls Bedrock made during a chat turn to the matching
// on-screen flow, reusing the already-fetched result instead of calling the
// MCP tool again.
async function handleBedrockToolCalls(toolCalls) {
  for (const call of toolCalls) {
    switch (call.name) {
      case "start_memory_game":
        showScreen("memory");
        await startMemoryGame(call.result);
        break;
      case "submit_memory_answer":
        if (current !== "memory") showScreen("memory");
        await renderMemoryResult(call.result);
        break;
      case "start_matching_game":
        showScreen("matching");
        await startMatchingGame(call.result);
        break;
      case "start_saying_game":
        showScreen("saying");
        await renderSayingQuestion(call.result);
        break;
      case "submit_saying_answer":
        if (current !== "saying") showScreen("saying");
        await renderSayingResult(call.result);
        break;
      case "start_category_game":
        showScreen("category");
        startCategoryRound(call.result);
        break;
      case "submit_category_answer":
        if (current !== "category") showScreen("category");
        await renderCategoryResult(call.result);
        break;
      case "start_stretch_routine":
        showScreen("stretch");
        startStretch(call.result);
        break;
      case "start_meditation":
        showScreen("meditation");
        el("meditation-select").classList.add("hidden");
        el("meditation-session").classList.remove("hidden");
        el("meditation-result").classList.add("hidden");
        startMeditation(call.args.meditation_id, call.result);
        break;
      case "log_completion":
        // call.result.error means the server guard refused it (stated
        // intent, not a completion) -- Vera's spoken reply already
        // explains why; there's nothing to render.
        if (call.result.error) break;
        if (current === "stretch") await renderActivityCompletion(call.result, "stretch-result");
        else if (current === "meditation") await renderActivityCompletion(call.result, "meditation-result");
        break;
      case "log_activity":
        if (call.result.error) break;
        showScreen("progress");
        await celebrate(call.result.new_milestones);
        break;
      case "get_fitness_log":
      case "get_streak":
      case "check_milestones":
      case "get_daily_summary":
        showScreen("progress");
        break;
      default:
        break;
    }
  }
}

function parseIntent(text) {
  const t = text.toLowerCase();
  if (/\b(home|main menu|go back)\b/.test(t)) return "home";
  if (/\b(memory|word game|remember)\b/.test(t)) return "memory";
  if (/\b(matching|match the|flip cards|pairs)\b/.test(t)) return "matching";
  if (/\b(saying|proverb|finish the)\b/.test(t)) return "saying";
  if (/\b(categor)\b/.test(t)) return "category";
  if (/\b(stretch|chair|exercise)\b/.test(t)) return "stretch";
  if (/\b(medit|calm|breath|relax)\b/.test(t)) return "meditation";
  if (/\b(progress|calendar|streak|badge|how am i doing)\b/.test(t)) return "progress";
  return null;
}

async function captureSpeech() {
  if (micListening) return;
  micListening = true;
  const mic = el("mic-btn");
  mic.classList.add("listening");
  Companion.setListening(true);
  const text = await listen();
  mic.classList.remove("listening");
  Companion.setListening(false);
  micListening = false;
  if (text) {
    routeUtterance(text);
  } else {
    await say("I didn't quite catch that. Try again, or type instead.");
  }
}

// ---------- home ----------

async function renderHome() {
  el("home-greeting").textContent = `${greetingWord()}`;
  el("home-sub").textContent = "Let's see what Vera has for you today.";
  updateHomeCheersBadge();
  let profile, streak;
  try {
    profile = await callTool("get_profile", { user_id: currentUserId });
    const log = await callTool("get_fitness_log", { user_id: currentUserId, days: 7 });
    streak = log.streak.current;
    el("home-greeting").textContent = `${greetingWord()}, ${profile.name}`;
    el("home-sub").textContent = streak > 0
      ? `You're on a ${streak} day streak. Keep it up!`
      : "Let's do something nice today.";
  } catch {
    el("home-sub").textContent = "Couldn't reach Vera's server. Is it running?";
    return;
  }

  // Proactive greeting: Vera speaks up first, once per app visit, pulling
  // in the daily summary, streak, an upcoming milestone, and a memory
  // herself. Coming back to Home later in the same visit just shows a
  // short caption -- no repeated spoken greeting until the app is opened
  // fresh again (a new page load resets greetedThisSession).
  if (!greetedThisSession) {
    greetedThisSession = true;
    let greeted = false;
    try {
      const result = await greet(currentUserId);
      conversationHistory = (result.history || []).slice(-MAX_HISTORY);
      if (result.reply) {
        await say(result.reply);
        greeted = true;
      }
    } catch {
      // Bedrock unavailable -- fall back to the simple greeting below.
    }
    if (!greeted) {
      await say(streak > 0
        ? `${greetingWord()}, ${profile.name}. You're on a ${streak} day streak!`
        : `${greetingWord()}, ${profile.name}. What would you like to do today?`);
    }
    await tryPlayNextCheer({ onAppOpen: true });
    return;
  }

  el("home-sub").textContent = "What would you like to do next?";
}

// Home's Cheers card shows a quick count of what's waiting, without
// revealing any content -- the full shelf lives on its own screen now.
async function updateHomeCheersBadge() {
  const badge = el("home-cheers-badge");
  let cheers;
  try {
    cheers = (await callTool("list_cheers", { user_id: currentUserId })).cheers;
  } catch {
    badge.classList.add("hidden");
    return;
  }
  const newCount = cheers.filter((c) => c.status === "unlocked").length;
  const lockedCount = cheers.filter((c) => c.status === "locked").length;
  if (!newCount && !lockedCount) {
    badge.classList.add("hidden");
    return;
  }
  const parts = [];
  if (newCount) parts.push(`${newCount} new`);
  if (lockedCount) parts.push(`${lockedCount} locked`);
  badge.textContent = parts.join(" · ");
  badge.classList.remove("hidden");
}

async function renderCheersScreen() {
  const content = el("cheers-content");
  content.innerHTML = `<div class="say-text">Loading…</div>`;
  let cheers;
  try {
    cheers = (await callTool("list_cheers", { user_id: currentUserId })).cheers;
  } catch {
    content.innerHTML = `<div class="say-text">Couldn't reach Vera's server.</div>`;
    return;
  }
  const unlocked = cheers.filter((c) => c.status === "unlocked");
  const played = cheers.filter((c) => c.status === "played");
  const lockedCount = cheers.filter((c) => c.status === "locked").length;

  if (!unlocked.length && !played.length && !lockedCount) {
    content.innerHTML = `<div class="say-text">No cheers from family yet.</div>`;
    return;
  }

  const groups = [];
  if (unlocked.length) {
    groups.push(`<h2 class="section-sub">New</h2><div class="family-shelf-list">`
      + unlocked.map((c) => `<button class="tile family-shelf-card" data-cheer-id="${escapeHtml(c.id)}">💜 A message from ${escapeHtml(c.family_name)}</button>`).join("")
      + `</div>`);
  }
  if (played.length) {
    groups.push(`<h2 class="section-sub">Played (tap to replay)</h2><div class="family-shelf-list">`
      + played.map((c) => `<button class="tile family-shelf-card played" data-cheer-id="${escapeHtml(c.id)}">↻ Replay ${escapeHtml(c.family_name)}'s message</button>`).join("")
      + `</div>`);
  }
  if (lockedCount) {
    groups.push(`<h2 class="section-sub">Still Locked</h2><div class="family-shelf-list">`
      + `<div class="tile family-shelf-card locked">🔒 ${lockedCount} surprise${lockedCount === 1 ? "" : "s"} from family waiting. Keep going to unlock ${lockedCount === 1 ? "it" : "them"}!</div>`
      + `</div>`);
  }
  content.innerHTML = groups.join("");
  content.querySelectorAll(".family-shelf-card[data-cheer-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cheer = cheers.find((c) => c.id === btn.dataset.cheerId);
      if (!cheer) return;
      await showCheerOverlay(cheer);
      if (cheer.status !== "played") {
        try { await callTool("mark_cheer_played", { cheer_id: cheer.id, user_id: currentUserId }); } catch { /* not fatal */ }
      }
      renderCheersScreen();
    });
  });
}

// ---------- games ----------

async function renderGamesList() {
  const list = el("games-list");
  list.innerHTML = `<div class="say-text">Loading…</div>`;
  let data;
  try {
    data = await callTool("list_sessions", {});
  } catch {
    list.innerHTML = `<div class="say-text">Couldn't reach Vera's server.</div>`;
    return;
  }
  list.innerHTML = data.games.map((g) => `
    <button class="tile" data-game-id="${escapeHtml(g.id)}">
      <span class="tile-icon">${GAME_ICONS[g.id] || "🎲"}</span>
      <span class="tile-label">${escapeHtml(g.title)}</span>
      <span class="tile-desc">${escapeHtml(g.description || "")}</span>
    </button>
  `).join("");
  list.querySelectorAll(".tile[data-game-id]").forEach((btn) => {
    btn.addEventListener("click", () => openGame(btn.dataset.gameId));
  });
}

function openGame(gameId) {
  switch (gameId) {
    case "memory_game":
      showScreen("memory");
      startMemoryGame();
      break;
    case "matching_game":
      showScreen("matching");
      startMatchingGame();
      break;
    case "saying_game":
      showScreen("saying");
      startSayingGame();
      break;
    case "category_game":
      showScreen("category");
      startCategoryGame();
      break;
    default:
      break;
  }
}

// ---------- memory game ----------

async function startMemoryGame(preloaded) {
  el("memory-result").classList.add("hidden");
  el("memory-again-btn").classList.add("hidden");
  el("memory-listen-btn").classList.add("hidden");
  el("memory-words").classList.add("hidden");
  el("memory-prompt").textContent = "Get ready…";
  let data = preloaded;
  if (!data) {
    try {
      data = await callTool("start_memory_game", { user_id: currentUserId });
    } catch (e) {
      el("memory-prompt").textContent = "Couldn't start the game. Is the Vera server running?";
      return;
    }
  }
  el("memory-words").innerHTML = data.words.map((w) => `<span class="word-chip">${escapeHtml(w)}</span>`).join("");
  el("memory-words").classList.remove("hidden");
  el("memory-prompt").textContent = "Listen carefully…";
  await say(data.say);
  if (current !== "memory") return;
  el("memory-words").classList.add("hidden");
  el("memory-prompt").textContent = "Now tell Vera the words you remember.";
  el("memory-listen-btn").classList.remove("hidden");
  pendingAnswer = submitMemoryAnswer;
}

async function renderMemoryResult(result) {
  pendingAnswer = null;
  el("memory-listen-btn").classList.add("hidden");
  el("memory-prompt").textContent = "";
  el("memory-result").textContent = `You remembered ${result.score} of ${result.total} words.`;
  el("memory-result").classList.remove("hidden");
  el("memory-again-btn").classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

async function submitMemoryAnswer(answer) {
  el("memory-prompt").textContent = "Let's see how you did…";
  let result;
  try {
    result = await callTool("submit_memory_answer", { answer, user_id: currentUserId });
  } catch {
    el("memory-prompt").textContent = "Something went wrong scoring that. Let's try again.";
    return;
  }
  await renderMemoryResult(result);
}

// ---------- matching pairs ----------

let matchingState = { cards: [], flipped: [], matched: [], attempts: 0, busy: false };

async function startMatchingGame(preloaded) {
  el("matching-result").classList.add("hidden");
  el("matching-again-btn").classList.add("hidden");
  el("matching-prompt").textContent = "Get ready…";
  el("matching-board").innerHTML = "";
  let data = preloaded;
  if (!data) {
    try {
      data = await callTool("start_matching_game", { user_id: currentUserId });
    } catch {
      el("matching-prompt").textContent = "Couldn't start the game. Is the Vera server running?";
      return;
    }
  }
  matchingState = { cards: data.cards, flipped: [], matched: [], attempts: 0, busy: false };
  renderMatchingBoard();
  el("matching-prompt").textContent = `Find the ${data.pairs} matching pairs.`;
  await say(data.say);
}

function renderMatchingBoard() {
  const board = el("matching-board");
  board.innerHTML = matchingState.cards.map((symbol, i) => {
    const isMatched = matchingState.matched.includes(i);
    const isFlipped = matchingState.flipped.includes(i) || isMatched;
    return `<button class="match-card${isFlipped ? " flipped" : ""}${isMatched ? " matched" : ""}" data-index="${i}" ${isMatched ? "disabled" : ""}>
      ${isFlipped ? escapeHtml(symbol) : "❓"}
    </button>`;
  }).join("");
  board.querySelectorAll(".match-card:not(.matched)").forEach((btn) => {
    btn.addEventListener("click", () => flipMatchingCard(Number(btn.dataset.index)));
  });
}

async function flipMatchingCard(index) {
  if (current !== "matching" || matchingState.busy) return;
  if (matchingState.flipped.includes(index) || matchingState.matched.includes(index)) return;
  matchingState.flipped.push(index);
  renderMatchingBoard();
  if (matchingState.flipped.length < 2) return;

  matchingState.busy = true;
  matchingState.attempts += 1;
  const [a, b] = matchingState.flipped;
  await sleep(700);
  if (matchingState.cards[a] === matchingState.cards[b]) {
    matchingState.matched.push(a, b);
  }
  matchingState.flipped = [];
  matchingState.busy = false;
  renderMatchingBoard();

  if (matchingState.matched.length === matchingState.cards.length) {
    await finishMatchingGame();
  }
}

async function finishMatchingGame() {
  el("matching-prompt").textContent = "";
  let result;
  try {
    result = await callTool("submit_matching_result", { attempts: matchingState.attempts, user_id: currentUserId });
  } catch {
    return;
  }
  el("matching-result").textContent = `Found all ${result.pairs} pairs in ${matchingState.attempts} tries!`;
  el("matching-result").classList.remove("hidden");
  el("matching-again-btn").classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

// ---------- finish the saying ----------

async function startSayingGame(preloaded) {
  el("saying-result").classList.add("hidden");
  el("saying-again-btn").classList.add("hidden");
  el("saying-prompt").textContent = "Get ready…";
  el("saying-choices").innerHTML = "";
  el("saying-progress").textContent = "";
  let data = preloaded;
  if (!data) {
    try {
      data = await callTool("start_saying_game", { user_id: currentUserId });
    } catch {
      el("saying-prompt").textContent = "Couldn't start the game. Is the Vera server running?";
      return;
    }
  }
  await renderSayingQuestion(data);
}

async function renderSayingQuestion(data) {
  el("saying-progress").textContent = `Question ${data.question_number} of ${data.total}`;
  el("saying-prompt").textContent = `"${data.beginning} ___"`;
  el("saying-choices").innerHTML = data.choices.map((c) => `
    <button class="tile" data-choice="${escapeHtml(c)}"><span class="tile-label">${escapeHtml(c)}</span></button>
  `).join("");
  el("saying-choices").querySelectorAll(".tile[data-choice]").forEach((btn) => {
    btn.addEventListener("click", () => submitSayingAnswer(btn.dataset.choice));
  });
  pendingAnswer = submitSayingAnswer;
  await say(data.say);
}

async function submitSayingAnswer(choice) {
  pendingAnswer = null;
  el("saying-choices").innerHTML = "";
  let result;
  try {
    result = await callTool("submit_saying_answer", { choice, user_id: currentUserId });
  } catch {
    el("saying-prompt").textContent = "Something went wrong. Let's try again.";
    return;
  }
  await renderSayingResult(result);
}

async function renderSayingResult(result) {
  if (!result.done) {
    const feedback = result.correct ? "That's right!" : `Not quite — it's "${result.answer}."`;
    el("saying-progress").textContent = feedback;
    await say(feedback);
    if (current !== "saying") return;
    await renderSayingQuestion(result);
    return;
  }
  el("saying-prompt").textContent = "";
  el("saying-progress").textContent = "";
  el("saying-result").textContent = `You got ${result.score} of ${result.total} right!`;
  el("saying-result").classList.remove("hidden");
  el("saying-again-btn").classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

// ---------- word categories ----------

async function startCategoryGame(preloaded) {
  el("category-result").classList.add("hidden");
  el("category-again-btn").classList.add("hidden");
  el("category-answer-row").classList.add("hidden");
  el("category-prompt").textContent = "Get ready…";
  let data = preloaded;
  if (!data) {
    try {
      data = await callTool("start_category_game", { user_id: currentUserId });
    } catch {
      el("category-prompt").textContent = "Couldn't start the game. Is the Vera server running?";
      return;
    }
  }
  await startCategoryRound(data);
}

async function startCategoryRound(data) {
  el("category-prompt").textContent = `Name as many ${data.category} as you can.`;
  await say(data.say);
  if (current !== "category") return;
  el("category-answer-row").classList.remove("hidden");
  pendingAnswer = submitCategoryAnswer;
}

async function submitCategoryAnswer(answer) {
  pendingAnswer = null;
  el("category-answer-row").classList.add("hidden");
  el("category-prompt").textContent = "Let's see…";
  let result;
  try {
    result = await callTool("submit_category_answer", { answer, user_id: currentUserId });
  } catch {
    el("category-prompt").textContent = "Something went wrong. Let's try again.";
    return;
  }
  await renderCategoryResult(result);
}

async function renderCategoryResult(result) {
  el("category-answer-row").classList.add("hidden");
  el("category-prompt").textContent = "";
  el("category-result").textContent = result.found.length
    ? `You named: ${result.found.join(", ")}.`
    : "No matches that time — let's try again!";
  el("category-result").classList.remove("hidden");
  el("category-again-btn").classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

// ---------- exercise ----------

async function renderExerciseList() {
  const list = el("exercise-list");
  list.innerHTML = `<div class="say-text">Loading…</div>`;
  let data;
  try {
    data = await callTool("list_sessions", {});
  } catch {
    list.innerHTML = `<div class="say-text">Couldn't reach Vera's server.</div>`;
    return;
  }
  const routineCards = data.stretch_routines.map((r) => `
    <button class="tile" data-routine-id="${escapeHtml(r.id)}">
      ${r.thumbnail_url ? `<img class="tile-thumb" src="${r.thumbnail_url}" alt="" />` : `<span class="tile-icon">🪑</span>`}
      <span class="tile-label">${escapeHtml(r.title)}</span>
      <span class="tile-desc">${r.minutes} minutes</span>
      ${r.available ? "" : `<span class="tile-badge">Video coming soon</span>`}
    </button>
  `).join("");
  const extraCards = `
    <button class="tile" data-action="log-activity">
      <span class="tile-icon">📝</span>
      <span class="tile-label">Log an Activity</span>
      <span class="tile-desc">Walk, bike, gardening, and more</span>
    </button>
    <button class="tile" data-action="start-walk">
      <span class="tile-icon">🚶</span>
      <span class="tile-label">Start a Walk</span>
      <span class="tile-desc">Vera keeps you company</span>
    </button>
    <button class="tile" data-action="start-ride">
      <span class="tile-icon">🚴</span>
      <span class="tile-label">Start a Ride</span>
      <span class="tile-desc">Vera keeps you company</span>
    </button>
  `;
  list.innerHTML = routineCards + extraCards;
  list.querySelectorAll(".tile[data-routine-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      showScreen("stretch");
      startStretch(undefined, btn.dataset.routineId);
    });
  });
  list.querySelector('[data-action="log-activity"]').addEventListener("click", () => showScreen("log-activity"));
  list.querySelector('[data-action="start-walk"]').addEventListener("click", () => startTimedActivity("walk", "Walk"));
  list.querySelector('[data-action="start-ride"]').addEventListener("click", () => startTimedActivity("bike", "Ride"));
}

// ---------- chair stretch ----------

async function renderActivityCompletion(result, resultElId) {
  el(resultElId).textContent = `Streak: ${result.streak.current} day${result.streak.current === 1 ? "" : "s"}.`;
  el(resultElId).classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

function renderStretchVideo(data) {
  const box = el("stretch-video");
  box.innerHTML = "";
  if (data.available && data.media_url) {
    box.classList.remove("video-placeholder");
    const video = document.createElement("video");
    video.src = data.media_url;
    video.muted = true;
    video.loop = true;
    video.autoplay = true;
    video.playsInline = true;
    box.appendChild(video);
  } else {
    box.classList.add("video-placeholder");
    box.innerHTML = `<span class="video-placeholder-icon">🎬</span><span class="video-placeholder-text">Video coming soon</span>`;
  }
}

async function startStretch(preloaded, routineId = "morning_chair_stretch") {
  bringBackFromDisplay("stretch-display-banner", "stretch-detail");
  el("stretch-result").classList.add("hidden");
  el("stretch-step-name").textContent = "Getting ready…";
  el("stretch-say").textContent = "";
  el("stretch-progress-fill").style.width = "0%";
  el("stretch-pause-btn").classList.remove("hidden");
  el("stretch-next-btn").classList.remove("hidden");
  let data = preloaded;
  if (!data) {
    try {
      data = await callTool("start_stretch_routine", { routine_id: routineId, user_id: currentUserId });
    } catch {
      el("stretch-step-name").textContent = "Couldn't start the stretch. Is the Vera server running?";
      return;
    }
  }
  el("stretch-title").textContent = data.title || "Chair Stretch";
  renderStretchVideo(data);
  await say(data.say);
  Companion.setVideoMode(true);
  for (const [stepIndex, step] of data.steps.entries()) {
    if (current !== "stretch") return;
    el("stretch-step-name").textContent = step.name;
    el("stretch-say").textContent = step.say;
    el("stretch-progress-fill").style.width = "0%";
    if (displayActive) {
      await pushDisplaySnapshot({
        type: "stretch", title: data.title, step_name: step.name, say: step.say,
        progress_percent: Math.round((stepIndex / data.steps.length) * 100),
      });
    }

    const spoken = say(step.say);
    const paced = animateProgress(step.seconds * 1000);
    const skipSignal = new Promise((resolve) => { skipStretchStep = resolve; });

    if (step.check_in) {
      await spoken;
      el("stretch-say").textContent += " (Tap the mic or type your answer — or just wait, and we'll keep going.)";
      await Promise.race([
        new Promise((resolve) => { pendingAnswer = (text) => { say(`Thanks for letting me know, ${text}.`).then(resolve); }; }),
        sleep(12000),
        skipSignal,
      ]);
      pendingAnswer = null;
      // Workout step break: at most one family cheer, same cap/rotation as anywhere else.
      if (current === "stretch") await tryPlayNextCheer();
    } else {
      await Promise.race([Promise.all([spoken, paced]), skipSignal]);
    }
    skipStretchStep = null;
    stopSpeaking();
  }
  Companion.setVideoMode(false);
  if (current !== "stretch") return;
  el("stretch-step-name").textContent = "All done!";
  el("stretch-say").textContent = "";
  el("stretch-progress-fill").style.width = "100%";
  el("stretch-pause-btn").classList.add("hidden");
  el("stretch-next-btn").classList.add("hidden");
  let result;
  try {
    result = await callTool("log_completion", {
      activity_type: "stretch",
      minutes: data.minutes,
      session_id: data.routine_id,
      user_id: currentUserId,
      completed: true,
      user_statement: "Completed via the app's own routine player.",
    });
  } catch {
    return;
  }
  await renderActivityCompletion(result, "stretch-result");
}

function animateProgress(durationMs) {
  const fill = el("stretch-progress-fill");
  const start = performance.now();
  return new Promise((resolve) => {
    function tick() {
      if (current !== "stretch") return resolve();
      const pct = Math.min(100, ((performance.now() - start) / durationMs) * 100);
      fill.style.width = `${pct}%`;
      if (pct >= 100) {
        resolve();
      } else {
        trackTimer(setTimeout(tick, 100));
      }
    }
    tick();
  });
}

let stretchPaused = false;

function toggleStretchPause() {
  stretchPaused = !stretchPaused;
  el("stretch-pause-btn").textContent = stretchPaused ? "Resume" : "Pause";
  // Coarse pause: whichever voice backend is talking, plus the step loop,
  // both respect this between steps; mid-step pausing isn't needed for a
  // hackathon demo.
  if (stretchPaused) pauseSpeaking();
  else resumeSpeaking();
}

// ---------- meditation ----------

async function renderMeditationList() {
  const list = el("meditation-select");
  list.innerHTML = `<div class="say-text">Loading…</div>`;
  let data;
  try {
    data = await callTool("list_sessions", {});
  } catch {
    list.innerHTML = `<div class="say-text">Couldn't reach Vera's server.</div>`;
    return;
  }
  if (!data.meditations.length) {
    list.innerHTML = `<div class="say-text">No meditations yet — check back soon.</div>`;
    return;
  }
  list.innerHTML = data.meditations.map((m) => `
    <button class="tile" data-med-id="${escapeHtml(m.id)}">
      ${m.thumbnail_url ? `<img class="tile-thumb" src="${m.thumbnail_url}" alt="" />` : `<span class="tile-icon">${m.type === "video" ? "🎬" : "🎧"}</span>`}
      <span class="tile-label">${escapeHtml(m.title)}</span>
      <span class="tile-desc">${m.minutes} minutes</span>
      ${m.available ? "" : `<span class="tile-badge">Coming soon</span>`}
    </button>
  `).join("");
  list.querySelectorAll(".tile[data-med-id]").forEach((btn) => {
    btn.addEventListener("click", () => startMeditation(btn.dataset.medId));
  });
}

// Whether a meditation track/timer is actively running right now -- so
// leaving the screen (Back, Home, voice nav, a /tv handoff, or just
// closing the tab) can stop it immediately and skip logging, since only
// an actual finish (the track's own "ended" event, or the synthetic
// countdown reaching zero) should count.
let meditationState = "idle"; // "idle" | "playing"

function pauseMeditationMedia() {
  const mediaEl = el("meditation-media-wrap").querySelector("audio, video");
  if (mediaEl) mediaEl.pause();
}

// Called when the person leaves mid-session by any route other than the
// track finishing on its own -- never logs, never credits the activity.
function stopMeditationEarly() {
  if (meditationState !== "playing") return;
  meditationState = "idle";
  pauseMeditationMedia();
  say("That's okay, we can finish another time.");
}

async function finishMeditation(data, meditationId) {
  if (current !== "meditation") return;
  let result;
  try {
    result = await callTool("log_completion", {
      activity_type: "meditation",
      minutes: data.minutes,
      session_id: meditationId,
      user_id: currentUserId,
      completed: true,
      user_statement: "Completed via the app's own meditation player.",
    });
  } catch {
    return;
  }
  await renderActivityCompletion(result, "meditation-result");
  el("meditation-session").classList.add("hidden");
  renderMeditationList();
}

// Real recording available: play it for real, with its own time as the clock.
function runRealMeditationMedia(data, meditationId) {
  return new Promise((resolve) => {
    const wrap = el("meditation-media-wrap");
    wrap.innerHTML = "";
    const mediaEl = document.createElement(data.type === "video" ? "video" : "audio");
    mediaEl.src = data.media_url;
    mediaEl.controls = true;
    if (data.type === "video") mediaEl.playsInline = true;
    wrap.appendChild(mediaEl);
    Companion.setVideoMode(true);
    meditationState = "playing";

    const finishIfStillHere = async (completed) => {
      if (meditationState !== "playing") { resolve(); return; } // already stopped early elsewhere
      meditationState = "idle";
      Companion.setVideoMode(false);
      if (completed) await finishMeditation(data, meditationId);
      resolve();
    };
    mediaEl.addEventListener("ended", () => finishIfStillHere(true));
    el("meditation-stop-btn").onclick = () => {
      mediaEl.pause();
      meditationState = "idle";
      Companion.setVideoMode(false);
      el("meditation-session").classList.add("hidden");
      renderMeditationList();
      say("That's okay, we can finish another time.");
      resolve();
    };
    mediaEl.play().catch(() => {});
  });
}

// No recording yet: fall back to a synthetic countdown for the target length.
async function runSyntheticMeditationTimer(data, meditationId) {
  let remaining = data.minutes * 60;
  const circle = el("meditation-circle");
  circle.classList.remove("hidden");
  const render = () => {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    circle.textContent = `${m}:${String(s).padStart(2, "0")}`;
  };
  render();
  Companion.setVideoMode(true);
  meditationState = "playing";

  const completed = await new Promise((resolve) => {
    const finish = (done) => { clearInterval(id); resolve(done); };
    el("meditation-stop-btn").onclick = () => {
      el("meditation-session").classList.add("hidden");
      renderMeditationList();
      say("That's okay, we can finish another time.");
      finish(false);
    };
    const id = trackTimer(setInterval(() => {
      remaining -= 1;
      render();
      if (remaining <= 0) finish(true);
    }, 1000));
  });
  if (meditationState !== "playing") return; // stopped early via another route already handled it
  meditationState = "idle";
  Companion.setVideoMode(false);
  if (completed) await finishMeditation(data, meditationId);
}

async function startMeditation(meditationId, preloaded) {
  bringBackFromDisplay("meditation-display-banner", "meditation-detail");
  el("meditation-select").classList.add("hidden");
  el("meditation-session").classList.remove("hidden");
  el("meditation-result").classList.add("hidden");
  el("meditation-media-wrap").innerHTML = "";
  el("meditation-circle").classList.add("hidden");
  let data = preloaded;
  if (!data) {
    try {
      data = await callTool("start_meditation", { meditation_id: meditationId, user_id: currentUserId });
    } catch {
      el("meditation-text").textContent = "Couldn't start meditation. Is the Vera server running?";
      return;
    }
  }
  el("meditation-text").textContent = data.title;
  await say(data.say);
  if (current !== "meditation") return;

  if (data.available && data.media_url) {
    await runRealMeditationMedia(data, meditationId);
  } else {
    await runSyntheticMeditationTimer(data, meditationId);
  }
}

// ---------- log an activity ----------

let logActivityState = { activity: null, minutes: null, feeling: null };

function showLogStep(step) {
  ["activity", "custom", "minutes", "feeling", "done"].forEach((s) => {
    el(`log-step-${s}`).classList.toggle("hidden", s !== step);
  });
}

function resetLogActivity() {
  logActivityState = { activity: null, minutes: null, feeling: null };
  el("log-custom-name").value = "";
  showLogStep("activity");
}

async function finishLogActivity(feeling) {
  logActivityState.feeling = feeling;
  showLogStep("done");
  el("log-result").textContent = "Logging…";
  let result;
  try {
    result = await callTool("log_activity", {
      activity: logActivityState.activity,
      minutes: logActivityState.minutes,
      feeling: logActivityState.feeling || undefined,
      user_id: currentUserId,
      completed: true,
      user_statement: "Logged via the app's Log an Activity screen.",
    });
  } catch {
    el("log-result").textContent = "Something went wrong logging that. Please try again.";
    return;
  }
  el("log-result").textContent =
    `Logged ${logActivityState.minutes} minutes of ${result.activity.replace("_", " ")}. `
    + `Streak: ${result.streak.current} day${result.streak.current === 1 ? "" : "s"}.`;
  await say(result.say);
  await celebrate(result.new_milestones);
}

// ---------- start a walk / start a ride ----------

let timedActivityKind = null;
let timedActivityElapsed = 0;

function startTimedActivity(kind, label) {
  timedActivityKind = kind;
  timedActivityElapsed = 0;
  el("timed-activity-title").textContent = label;
  el("timed-activity-result").classList.add("hidden");
  el("timed-activity-circle").textContent = "0:00";
  showScreen("timed-activity");

  const renderClock = () => {
    const m = Math.floor(timedActivityElapsed / 60);
    const s = timedActivityElapsed % 60;
    el("timed-activity-circle").textContent = `${m}:${String(s).padStart(2, "0")}`;
  };
  trackTimer(setInterval(() => {
    timedActivityElapsed += 1;
    renderClock();
  }, 1000));

  let encIndex = 0;
  trackTimer(setInterval(() => {
    if (current !== "timed-activity") return;
    say(ENCOURAGEMENTS[encIndex % ENCOURAGEMENTS.length]);
    encIndex += 1;
  }, 180000));

  say(`Alright, let's get started. I'll check in with you every few minutes. Tap I'm Done whenever you're ready to stop.`);
}

async function finishTimedActivity() {
  const minutes = Math.max(1, Math.round(timedActivityElapsed / 60));
  clearActiveTimers();
  let result;
  try {
    result = await callTool("log_activity", {
      activity: timedActivityKind, minutes, user_id: currentUserId,
      completed: true, user_statement: "Logged via the app's own timer -- \"I'm Done\" was tapped.",
    });
  } catch {
    return;
  }
  el("timed-activity-result").textContent =
    `Logged ${minutes} minute${minutes === 1 ? "" : "s"}. Streak: ${result.streak.current} day${result.streak.current === 1 ? "" : "s"}.`;
  el("timed-activity-result").classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

// ---------- progress / fitness log ----------

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

async function renderProgress() {
  el("progress-streak").textContent = "Loading…";
  el("progress-calendar").innerHTML = "";
  el("progress-badges").innerHTML = "";
  el("progress-calendar-weekday-row").innerHTML = WEEKDAY_LABELS.map((w) => `<span>${w}</span>`).join("");
  el("for-family-link").href = `/caregiver/${encodeURIComponent(currentUserId)}`;
  let log;
  try {
    log = await callTool("get_fitness_log", { user_id: currentUserId, days: 28 });
  } catch {
    el("progress-streak").textContent = "Couldn't reach Vera's server.";
    return;
  }
  el("progress-streak").textContent =
    `${log.streak.current} day streak (longest: ${log.streak.longest}) — ${log.total_minutes} minutes total`;
  el("progress-week").textContent =
    `This week: ${log.week.active_days} of ${log.week.goal_days} active days, ` +
    `${log.week.active_minutes} active minutes` +
    (log.week.goal_met ? " — goal met!" : "");

  const dayLabel = (iso) => new Date(iso + "T00:00:00").getDate();
  el("progress-calendar").innerHTML = log.calendar_weeks.flat().map((d) => {
    const classes = ["cal-cell"];
    if (d.active) classes.push("active");
    if (d.is_today) classes.push("today");
    if (d.is_future) classes.push("future");
    return `<div class="${classes.join(" ")}" data-date="${d.date}" title="${d.date}">
      <span>${dayLabel(d.date)}</span>${d.active ? `<span class="cal-check">✓</span>` : ""}
    </div>`;
  }).join("");
  el("progress-calendar").querySelectorAll(".cal-cell:not(.future)").forEach((cell) => {
    cell.addEventListener("click", () => showDayDetail(cell.dataset.date));
  });

  el("progress-badges").innerHTML = !log.badges_summary.length
    ? `<div class="say-text">No badges yet — they're on the way!</div>`
    : log.badges_summary.map((b) => `<div class="badge">🏅 ${escapeHtml(b.title)}${b.count > 1 ? ` ×${b.count}` : ""}</div>`).join("");

  let trends = [];
  try {
    trends = (await callTool("get_engagement_trends", { user_id: currentUserId })).trends;
  } catch {
    // Engagement trends are a nice-to-have -- the rest of Progress still works.
  }
  el("progress-engagement").innerHTML = trends.length
    ? trends.map((t) => `<div class="say-text">${escapeHtml(t.label)}${t.response_note ? " " + escapeHtml(t.response_note) : ""}</div>`).join("")
    : `<div class="say-text">Play a few games this month to see how it's going.</div>`;
}

const GAME_TYPES = new Set(["memory_game", "matching_game", "saying_game", "category_game"]);

function describeActivity(a) {
  const label = a.type.replace(/_/g, " ");
  if (GAME_TYPES.has(a.type)) {
    const d = a.details || {};
    if ("score" in d && "total" in d) return `${label}: ${d.score} of ${d.total}`;
    if ("count" in d && "target" in d) return `${label}: named ${d.count} of ${d.target}`;
    if ("attempts" in d) return `${label}: ${d.attempts} flips`;
    return label;
  }
  const feeling = a.details && a.details.feeling ? `, felt ${a.details.feeling}` : "";
  return `${label}: ${a.minutes} minutes${feeling}`;
}

async function showDayDetail(dateIso) {
  const overlay = el("day-detail-overlay");
  const body = el("day-detail-body");
  el("day-detail-title").textContent = new Date(dateIso + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  body.innerHTML = `<p class="say-text">Loading…</p>`;
  overlay.classList.remove("hidden");
  let detail;
  try {
    detail = await callTool("get_day_detail", { user_id: currentUserId, on_date: dateIso });
  } catch {
    body.innerHTML = `<p class="say-text">Couldn't reach Vera's server.</p>`;
    return;
  }
  const parts = [];
  parts.push(detail.activities.length
    ? `<h3 class="section-sub">Activities</h3><ul class="day-detail-list">${detail.activities.map((a) => `<li>${escapeHtml(describeActivity(a))}</li>`).join("")}</ul>`
    : `<p class="say-text">Nothing logged this day.</p>`);
  if (detail.badges.length) {
    parts.push(`<h3 class="section-sub">Badges Earned</h3><ul class="day-detail-list">${detail.badges.map((b) => `<li>🏅 ${escapeHtml(b.title)}</li>`).join("")}</ul>`);
  }
  if (detail.cheers_played.length) {
    parts.push(`<h3 class="section-sub">Cheers Played</h3><ul class="day-detail-list">${detail.cheers_played.map((c) => `<li>💜 A message from ${escapeHtml(c.family_name)}</li>`).join("")}</ul>`);
  }
  body.innerHTML = parts.join("");
}

// ---------- wiring ----------

function init() {
  Companion.init();
  setInterval(tickClock, 1000);
  tickClock();

  el("home-btn").addEventListener("click", () => showScreen(currentUserId ? "home" : "start"));
  el("back-btn").addEventListener("click", goBack);
  el("day-detail-close-btn").addEventListener("click", () => el("day-detail-overlay").classList.add("hidden"));
  el("switch-profile-btn").addEventListener("click", () => showScreen("start"));

  el("add-profile-btn").addEventListener("click", () => {
    el("add-profile-form").classList.toggle("hidden");
    el("add-profile-name").focus();
  });
  const createProfile = async () => {
    const name = el("add-profile-name").value.trim();
    if (!name) return;
    try {
      const created = await callTool("create_profile", { name });
      el("add-profile-name").value = "";
      el("add-profile-form").classList.add("hidden");
      selectProfile(created.user_id);
    } catch {
      await say("I couldn't create that profile. Let's try again.");
    }
  };
  el("add-profile-save").addEventListener("click", createProfile);
  el("add-profile-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") createProfile();
  });

  document.querySelectorAll("#screen-home .tile[data-intent]").forEach((btn) => {
    btn.addEventListener("click", () => showScreen(btn.dataset.intent));
  });

  document.querySelectorAll("#log-step-activity .tile[data-activity]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const activity = btn.dataset.activity;
      if (activity === "other") {
        showLogStep("custom");
        el("log-custom-name").focus();
      } else {
        logActivityState.activity = activity;
        showLogStep("minutes");
      }
    });
  });
  const confirmCustomActivity = () => {
    const name = el("log-custom-name").value.trim();
    if (!name) return;
    logActivityState.activity = name;
    showLogStep("minutes");
  };
  el("log-custom-next").addEventListener("click", confirmCustomActivity);
  el("log-custom-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") confirmCustomActivity();
  });
  document.querySelectorAll("#log-step-minutes .tile[data-minutes]").forEach((btn) => {
    btn.addEventListener("click", () => {
      logActivityState.minutes = Number(btn.dataset.minutes);
      showLogStep("feeling");
    });
  });
  document.querySelectorAll("#log-step-feeling [data-feeling]").forEach((btn) => {
    btn.addEventListener("click", () => finishLogActivity(btn.dataset.feeling));
  });
  el("log-feeling-skip").addEventListener("click", () => finishLogActivity(null));
  el("log-again-btn").addEventListener("click", resetLogActivity);
  el("timed-activity-done-btn").addEventListener("click", finishTimedActivity);

  el("memory-listen-btn").addEventListener("click", captureSpeech);
  el("memory-again-btn").addEventListener("click", () => startMemoryGame());

  el("matching-again-btn").addEventListener("click", () => startMatchingGame());
  el("saying-again-btn").addEventListener("click", () => startSayingGame());
  el("category-listen-btn").addEventListener("click", captureSpeech);
  el("category-again-btn").addEventListener("click", () => startCategoryGame());

  el("stretch-pause-btn").addEventListener("click", toggleStretchPause);
  el("stretch-next-btn").addEventListener("click", () => {
    if (skipStretchStep) skipStretchStep();
  });
  el("stretch-to-tv-btn").addEventListener("click", () => sendToDisplay(
    { type: "stretch", title: el("stretch-title").textContent, step_name: el("stretch-step-name").textContent, say: el("stretch-say").textContent, progress_percent: 0 },
    "stretch-display-banner", "stretch-detail",
  ));
  el("stretch-bring-back-btn").addEventListener("click", () => bringBackFromDisplay("stretch-display-banner", "stretch-detail"));
  el("meditation-to-tv-btn").addEventListener("click", () => {
    // The TV mirrors the session; the main screen's own copy of the audio
    // stops rather than keep playing invisibly behind the banner.
    pauseMeditationMedia();
    sendToDisplay(
      { type: "meditation", title: "Meditation", say: el("meditation-text").textContent },
      "meditation-display-banner", "meditation-detail",
    );
  });
  el("meditation-bring-back-btn").addEventListener("click", () => bringBackFromDisplay("meditation-display-banner", "meditation-detail"));

  el("mic-btn").addEventListener("click", captureSpeech);

  el("type-toggle").addEventListener("click", () => {
    el("type-row").classList.toggle("hidden");
    if (!el("type-row").classList.contains("hidden")) el("type-input").focus();
  });

  const sendTyped = () => {
    const input = el("type-input");
    const text = input.value.trim();
    input.value = "";
    if (text) routeUtterance(text);
  };
  el("type-send").addEventListener("click", sendTyped);
  el("type-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendTyped();
  });

  if (!speechRecognitionSupported()) {
    el("mic-hint").textContent = "Voice input isn't supported in this browser — type instead.";
    el("type-row").classList.remove("hidden");
  }

  const remembered = getRememberedUserId();
  if (remembered) {
    currentUserId = remembered;
    showScreen("home");
  } else {
    showScreen("start");
  }
}

document.addEventListener("DOMContentLoaded", init);
