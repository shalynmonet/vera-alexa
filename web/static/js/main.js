import { callTool, chat } from "./api.js";
import { speak, listen, speechRecognitionSupported } from "./speech.js";
import { Companion } from "./companion.js";

const SCREENS = ["start", "home", "games", "memory", "exercise", "stretch", "meditation", "progress"];
const MAX_HISTORY = 20;
const REMEMBERED_USER_KEY = "vera_user_id";
let conversationHistory = [];
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
  clearActiveTimers();
  Companion.setVideoMode(false);
  SCREENS.forEach((s) => el(`screen-${s}`).classList.toggle("hidden", s !== name));
  current = name;
  Companion.placeInScreen(name);
  if (name === "start") renderStart();
  if (name === "home") renderHome();
  if (name === "games") renderGamesList();
  if (name === "exercise") renderExerciseList();
  if (name === "meditation") {
    el("meditation-select").classList.remove("hidden");
    el("meditation-session").classList.add("hidden");
  }
  if (name === "progress") renderProgress();
}

async function say(text) {
  if (!text) return;
  const mic = el("mic-btn");
  await Companion.say(text, (t) => speak(t, {
    onStart: () => mic.classList.add("speaking"),
    onEnd: () => mic.classList.remove("speaking"),
  }));
}

async function celebrate(milestones) {
  if (!milestones || !milestones.length) return;
  const overlay = el("celebration");
  const titleEl = el("celebrate-title");
  overlay.classList.remove("hidden");
  for (const m of milestones) {
    titleEl.textContent = m.title;
    const mic = el("mic-btn");
    await Companion.celebrate(m.celebration || `Congratulations, you earned ${m.title}!`, (t) => speak(t, {
      onStart: () => mic.classList.add("speaking"),
      onEnd: () => mic.classList.remove("speaking"),
    }));
    await sleep(800);
  }
  overlay.classList.add("hidden");
  titleEl.textContent = "";
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
  if (intent === "stretch") { showScreen("stretch"); startStretch(); return; }
  if (intent === "meditation") { showScreen("meditation"); return; }
  if (intent === "progress") { showScreen("progress"); return; }
  await say(`I heard "${text}". Try saying memory game, chair stretch, meditation, or my progress.`);
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
        if (current === "stretch") await renderActivityCompletion(call.result, "stretch-result");
        else if (current === "meditation") await renderActivityCompletion(call.result, "meditation-result");
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
  try {
    const profile = await callTool("get_profile", { user_id: currentUserId });
    const log = await callTool("get_fitness_log", { user_id: currentUserId, days: 7 });
    el("home-greeting").textContent = `${greetingWord()}, ${profile.name}`;
    const streak = log.streak.current;
    el("home-sub").textContent = streak > 0
      ? `You're on a ${streak} day streak. Keep it up!`
      : "Let's do something nice today.";
    await say(streak > 0
      ? `${greetingWord()}, ${profile.name}. You're on a ${streak} day streak!`
      : `${greetingWord()}, ${profile.name}. What would you like to do today?`);
  } catch {
    el("home-sub").textContent = "Couldn't reach Vera's server. Is it running?";
  }
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
      <span class="tile-icon">🧠</span>
      <span class="tile-label">${escapeHtml(g.title)}</span>
      <span class="tile-desc">${escapeHtml(g.description || "")}</span>
    </button>
  `).join("");
  list.querySelectorAll(".tile[data-game-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      showScreen("memory");
      startMemoryGame();
    });
  });
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
  list.innerHTML = data.stretch_routines.map((r) => `
    <button class="tile" data-routine-id="${escapeHtml(r.id)}">
      <span class="tile-icon">🪑</span>
      <span class="tile-label">${escapeHtml(r.title)}</span>
      <span class="tile-desc">${r.minutes} minutes</span>
    </button>
  `).join("");
  list.querySelectorAll(".tile[data-routine-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      showScreen("stretch");
      startStretch(undefined, btn.dataset.routineId);
    });
  });
}

// ---------- chair stretch ----------

async function renderActivityCompletion(result, resultElId) {
  el(resultElId).textContent = `Streak: ${result.streak.current} day${result.streak.current === 1 ? "" : "s"}.`;
  el(resultElId).classList.remove("hidden");
  await say(result.say);
  await celebrate(result.new_milestones);
}

async function startStretch(preloaded, routineId = "morning_chair_stretch") {
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
  await say(data.say);
  Companion.setVideoMode(true);
  for (const step of data.steps) {
    if (current !== "stretch") return;
    el("stretch-step-name").textContent = step.name;
    el("stretch-say").textContent = step.say;
    el("stretch-progress-fill").style.width = "0%";

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
    } else {
      await Promise.race([Promise.all([spoken, paced]), skipSignal]);
    }
    skipStretchStep = null;
    speechSynthesis.cancel();
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
  // Coarse pause: speechSynthesis + the step loop both respect this between
  // steps; mid-step pausing isn't needed for a hackathon demo.
  if (stretchPaused) speechSynthesis.pause();
  else speechSynthesis.resume();
}

// ---------- meditation ----------

async function startMeditation(meditationId, preloaded) {
  el("meditation-select").classList.add("hidden");
  el("meditation-session").classList.remove("hidden");
  el("meditation-result").classList.add("hidden");
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
  say(data.say);

  let remaining = data.minutes * 60;
  const render = () => {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    el("meditation-circle").textContent = `${m}:${String(s).padStart(2, "0")}`;
  };
  render();
  Companion.setVideoMode(true);

  await new Promise((resolve) => {
    const finish = () => { clearInterval(id); resolve(); };
    el("meditation-stop-btn").onclick = finish;
    const id = trackTimer(setInterval(() => {
      remaining -= 1;
      render();
      if (remaining <= 0) finish();
    }, 1000));
  });
  Companion.setVideoMode(false);
  if (current !== "meditation") return;

  let result;
  try {
    result = await callTool("log_completion", {
      activity_type: "meditation",
      minutes: data.minutes,
      session_id: meditationId,
      user_id: currentUserId,
    });
  } catch {
    return;
  }
  await renderActivityCompletion(result, "meditation-result");
  el("meditation-select").classList.remove("hidden");
  el("meditation-session").classList.add("hidden");
}

// ---------- progress / fitness log ----------

async function renderProgress() {
  el("progress-streak").textContent = "Loading…";
  el("progress-calendar").innerHTML = "";
  el("progress-badges").innerHTML = "";
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
    `This week: ${log.week.active_days} of ${log.week.goal_days} active days` +
    (log.week.goal_met ? " — goal met!" : "");

  const dayLabel = (iso) => new Date(iso + "T00:00:00").getDate();
  el("progress-calendar").innerHTML = log.calendar
    .map((d) => `<div class="cal-cell${d.active ? " active" : ""}" title="${d.date}">${dayLabel(d.date)}</div>`)
    .join("");

  if (!log.milestones.length) {
    el("progress-badges").innerHTML = `<div class="say-text">No badges yet — they're on the way!</div>`;
  } else {
    el("progress-badges").innerHTML = log.milestones
      .map((m) => `<div class="badge">🏅 ${escapeHtml(m.title)}</div>`)
      .join("");
  }
}

// ---------- wiring ----------

function init() {
  Companion.init();
  setInterval(tickClock, 1000);
  tickClock();

  el("home-btn").addEventListener("click", () => showScreen(currentUserId ? "home" : "start"));
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

  document.querySelectorAll("#meditation-select .tile[data-med]").forEach((btn) => {
    btn.addEventListener("click", () => startMeditation(btn.dataset.med));
  });

  el("memory-listen-btn").addEventListener("click", captureSpeech);
  el("memory-again-btn").addEventListener("click", () => startMemoryGame());

  el("stretch-pause-btn").addEventListener("click", toggleStretchPause);
  el("stretch-next-btn").addEventListener("click", () => {
    if (skipStretchStep) skipStretchStep();
  });

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
