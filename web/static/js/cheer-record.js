// Family Cheers: a family member's private, no-login record page. Standalone
// -- not part of the main Vera app's screen router, speech pipeline, or
// companion. Plain browser MediaRecorder, 15 second max, preview/re-record/send.

const MAX_SECONDS = 15;
const token = window.location.pathname.split("/").filter(Boolean).pop();
const presetMilestone = new URLSearchParams(window.location.search).get("milestone");

const el = (id) => document.getElementById(id);

let ctx = null; // the /api/cheer/context response
let called = ""; // what this family member calls the person (nickname, or their first name)
let recipientFirst = "";

let mode = null; // "voice" | "voice_photo" | "video"
let pendingCheer = null; // {cheer_type, target} set when sending -- from a suggestion tap or the "when" selector
let stream = null;
let recorder = null;
let chunks = [];
let blob = null;
let photoBlob = null;
let timerInterval = null;
let elapsed = 0;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function show(id) {
  ["loading", "invalid", "welcome", "main", "edit", "recorder", "sent"].forEach((s) => el(s).classList.toggle("hidden", s !== id));
}

async function fetchContext() {
  const res = await fetch(`/api/cheer/context/${token}`);
  const data = await res.json();
  if (!data.valid) return null;
  return data;
}

async function updateMember(fields) {
  const res = await fetch(`/api/cheer/update_member/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return res.json();
}

async function init() {
  try {
    ctx = await fetchContext();
  } catch {
    ctx = null;
  }
  if (!ctx) { show("invalid"); return; }

  recipientFirst = ctx.recipient_name.split(" ")[0];
  called = ctx.member.nickname || recipientFirst;

  if (!ctx.member.onboarded) {
    showWelcome();
  } else {
    showMain();
  }

  el("setup-relationship").addEventListener("change", () => {
    el("setup-relationship-other").classList.toggle("hidden", el("setup-relationship").value !== "Other");
  });
  el("setup-save-btn").addEventListener("click", saveWelcome);
  el("edit-cancel-btn").addEventListener("click", showMain);
  el("edit-save-btn").addEventListener("click", saveEdit);
  el("edit-details-link").addEventListener("click", showEdit);
  el("record-own-btn").addEventListener("click", () => openRecorder(null));
  el("mode-voice-btn").addEventListener("click", () => chooseMode("voice"));
  el("mode-voice-photo-btn").addEventListener("click", () => chooseMode("voice_photo"));
  el("mode-video-btn").addEventListener("click", () => chooseMode("video"));
  el("photo-input").addEventListener("change", onPhotoChosen);
  el("upload-input").addEventListener("change", onFileChosen);
  el("start-btn").addEventListener("click", startRecording);
  el("stop-btn").addEventListener("click", stopRecording);
  el("rerecord-btn").addEventListener("click", resetRecording);
  el("send-btn").addEventListener("click", sendCheer);
  el("sent-another-btn").addEventListener("click", showMain);
}

// ---------- welcome (first visit) ----------

function showWelcome() {
  el("welcome-title").textContent = `Welcome! Let's get you set up to cheer on ${recipientFirst}.`;
  el("welcome-sub").textContent = `You'll be recording short cheers for ${recipientFirst} -- let's start with a few quick details.`;
  el("setup-name").value = ctx.member.name || "";
  el("setup-nickname-label").textContent = `What do you call ${recipientFirst}?`;
  el("setup-nickname").value = ctx.member.nickname || "";
  el("setup-email").value = ctx.member.email || "";
  el("setup-email-optin-label").textContent = `Email me when ${recipientFirst} is close to a milestone or running low on my cheers.`;
  show("welcome");
}

async function saveWelcome() {
  const name = el("setup-name").value.trim();
  const relRaw = el("setup-relationship").value;
  const relationship = relRaw === "Other" ? el("setup-relationship-other").value.trim() : relRaw;
  const nickname = el("setup-nickname").value.trim();
  const email = el("setup-email").value.trim();
  const emailOptIn = el("setup-email-optin").checked;
  if (!relationship) { el("setup-relationship").focus(); return; }
  const { member } = await updateMember({ name, relationship, nickname: nickname || undefined, email: email || undefined, email_opt_in: emailOptIn });
  ctx.member = member;
  called = member.nickname || recipientFirst;
  ctx = await fetchContext();
  showMain();
}

// ---------- edit details ----------

function showEdit() {
  el("edit-nickname").value = ctx.member.nickname || "";
  el("edit-email").value = ctx.member.email || "";
  el("edit-email-optin").checked = !!ctx.member.email_opt_in;
  show("edit");
}

async function saveEdit() {
  const nickname = el("edit-nickname").value.trim();
  const email = el("edit-email").value.trim();
  const { member } = await updateMember({ nickname: nickname || undefined, email: email || undefined, email_opt_in: el("edit-email-optin").checked });
  ctx.member = member;
  called = member.nickname || recipientFirst;
  showMain();
}

// ---------- main hub ----------

function promptCard(p) {
  const note = p.note ? ` <span class="say-text">(${escapeHtml(p.note)})</span>` : "";
  return `<button class="tile family-shelf-card prompt-card" data-type="${escapeHtml(p.cheer_type)}" data-target="${escapeHtml(p.target || "")}" data-script="${escapeHtml(p.script)}">"${escapeHtml(p.script)}"${note}</button>`;
}

let autoOpenedMilestone = false;

function showMain() {
  if (presetMilestone && !autoOpenedMilestone) {
    autoOpenedMilestone = true;
    const match = ctx.prompts.coming_up.find((p) => p.target === presetMilestone);
    if (match) { openRecorder(match); return; }
  }
  el("main-title").textContent = `Help ${called} keep going 💜`;
  el("main-progress").textContent = `${ctx.sent_count} of ${ctx.goal} sent`;
  el("main-message").textContent =
    `One cheer is wonderful. Five means ${called} hears from you again and again: on her best days, when she reaches a goal, ` +
    `and on the days she needs a little push. Families who stay involved help their loved ones stay active, and a 15 second ` +
    `message from you might be the best part of her day.`;

  const groups = [];
  if (ctx.prompts.coming_up.length) groups.push(`<h2 class="section-sub">Coming Up</h2>` + ctx.prompts.coming_up.map(promptCard).join(""));
  groups.push(`<h2 class="section-sub">Anytime</h2>` + ctx.prompts.anytime.map(promptCard).join(""));
  if (ctx.prompts.activity.length) groups.push(`<h2 class="section-sub">About Their Activities</h2>` + ctx.prompts.activity.map(promptCard).join(""));
  el("suggestions").innerHTML = groups.join("");
  el("suggestions").querySelectorAll(".prompt-card").forEach((btn) => {
    btn.addEventListener("click", () => openRecorder({ cheer_type: btn.dataset.type, target: btn.dataset.target || null, script: btn.dataset.script }));
  });

  show("main");
}

// ---------- recorder ----------

function whenOptions() {
  const opts = [`<option value="anytime">Anytime</option>`];
  ctx.prompts.coming_up.forEach((p) => opts.push(`<option value="milestone:${escapeHtml(p.target)}">When they reach: ${escapeHtml(p.script.replace(/^Congrats on your /i, "").replace(/!$/, ""))}</option>`));
  ctx.prompts.activity.forEach((p) => opts.push(`<option value="activity:${escapeHtml(p.target)}">After their next ${escapeHtml(p.target.replace(/_/g, " "))}</option>`));
  return opts.join("");
}

function openRecorder(preset) {
  resetRecorder();
  if (preset) {
    pendingCheer = { cheer_type: preset.cheer_type, target: preset.target };
    el("cheer-sub").textContent = `Say something like: "${preset.script}"`;
    el("when-row").classList.add("hidden");
  } else {
    pendingCheer = null;
    el("cheer-sub").textContent = `Record your own message for ${called}.`;
    el("when-select").innerHTML = whenOptions();
    el("when-row").classList.remove("hidden");
  }
  el("cheer-title").textContent = `Record a cheer for ${recipientFirst}`;
  show("recorder");
}

async function chooseMode(m) {
  mode = m;
  el("mode-row").classList.add("hidden");
  if (m === "voice_photo") {
    el("photo-row").classList.remove("hidden");
    return; // wait for a photo to be chosen before showing the recorder
  }
  await startStream();
}

async function onPhotoChosen(e) {
  const file = e.target.files[0];
  if (!file) return;
  photoBlob = file;
  el("photo-preview").src = URL.createObjectURL(file);
  el("photo-preview").classList.remove("hidden");
  await startStream();
}

async function startStream() {
  el("record-area").classList.remove("hidden");
  el("upload-input").accept = mode === "video" ? "video/*" : "audio/*";
  try {
    stream = await navigator.mediaDevices.getUserMedia(mode === "video" ? { audio: true, video: true } : { audio: true });
  } catch {
    // No mic/camera access (denied, none on this device, etc) -- not a
    // dead end: "Upload a File Instead" (already visible alongside
    // Record) still works, so just explain why Record itself won't.
    el("cheer-sub").textContent = "Vera couldn't access your microphone or camera -- you can upload a file instead, or allow access and reload the page.";
    return;
  }
  if (mode === "video") {
    const v = el("preview-video");
    v.srcObject = stream;
    v.classList.remove("hidden");
    v.play().catch(() => {});
  }
}

function renderTimer() {
  el("timer").textContent = `0:${String(elapsed).padStart(2, "0")} / 0:${String(MAX_SECONDS).padStart(2, "0")}`;
}

function startRecording() {
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = onRecordingStopped;
  recorder.start();
  elapsed = 0;
  renderTimer();
  el("start-btn").classList.add("hidden");
  el("stop-btn").classList.remove("hidden");
  timerInterval = setInterval(() => {
    elapsed += 1;
    renderTimer();
    if (elapsed >= MAX_SECONDS) stopRecording();
  }, 1000);
}

function stopRecording() {
  clearInterval(timerInterval);
  if (recorder && recorder.state !== "inactive") recorder.stop();
}

function onRecordingStopped() {
  blob = new Blob(chunks, { type: mode === "video" ? "video/webm" : "audio/webm" });
  stream.getTracks().forEach((t) => t.stop());
  showPreview();
}

function showPreview() {
  el("record-area").classList.add("hidden");
  el("preview-area").classList.remove("hidden");
  const url = URL.createObjectURL(blob);
  if (mode === "video") {
    el("playback-video").src = url;
    el("playback-video").classList.remove("hidden");
  } else {
    el("playback-audio").src = url;
    el("playback-audio").classList.remove("hidden");
    if (mode === "voice_photo" && photoBlob) {
      el("playback-photo").src = URL.createObjectURL(photoBlob);
      el("playback-photo").classList.remove("hidden");
    }
  }
}

// Reads a local audio/video file's duration without uploading it, so an
// over-length file is caught before sending -- same way a live recording
// is capped while it's happening instead of after the fact.
function readMediaDuration(file, isVideo) {
  return new Promise((resolve, reject) => {
    const probe = document.createElement(isVideo ? "video" : "audio");
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      URL.revokeObjectURL(probe.src);
      resolve(probe.duration);
    };
    probe.onerror = () => reject(new Error("couldn't read that file"));
    probe.src = URL.createObjectURL(file);
  });
}

async function onFileChosen(e) {
  const file = e.target.files[0];
  if (!file) return;
  const isVideo = mode === "video";
  const wantPrefix = isVideo ? "video/" : "audio/";
  if (!(file.type || "").startsWith(wantPrefix)) {
    el("cheer-sub").textContent = `Please choose a${isVideo ? " video" : "n audio"} file.`;
    el("upload-input").value = "";
    return;
  }
  let duration;
  try {
    duration = await readMediaDuration(file, isVideo);
  } catch {
    el("cheer-sub").textContent = "Vera couldn't read that file -- please try another.";
    el("upload-input").value = "";
    return;
  }
  if (!isFinite(duration) || duration <= 0) {
    el("cheer-sub").textContent = "That file looks empty -- please try another.";
    el("upload-input").value = "";
    return;
  }
  if (duration > MAX_SECONDS + 1) {
    el("cheer-sub").textContent = `That clip is ${Math.round(duration)} seconds -- please choose one under ${MAX_SECONDS} seconds.`;
    el("upload-input").value = "";
    return;
  }
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  blob = file;
  elapsed = Math.min(MAX_SECONDS, Math.round(duration));
  showPreview();
}

function resetRecorder() {
  mode = null;
  blob = null;
  photoBlob = null;
  elapsed = 0;
  el("mode-row").classList.remove("hidden");
  el("photo-row").classList.add("hidden");
  el("photo-preview").classList.add("hidden");
  el("photo-input").value = "";
  el("upload-input").value = "";
  el("record-area").classList.add("hidden");
  el("preview-area").classList.add("hidden");
  el("playback-video").classList.add("hidden");
  el("playback-audio").classList.add("hidden");
  el("playback-photo").classList.add("hidden");
  el("start-btn").classList.remove("hidden");
  el("stop-btn").classList.add("hidden");
  const sendBtn = el("send-btn");
  sendBtn.disabled = false;
  sendBtn.textContent = "Send";
}

function resetRecording() {
  blob = null;
  elapsed = 0;
  el("upload-input").value = "";
  el("playback-video").classList.add("hidden");
  el("playback-audio").classList.add("hidden");
  el("playback-photo").classList.add("hidden");
  el("preview-area").classList.add("hidden");
  el("start-btn").classList.remove("hidden");
  el("stop-btn").classList.add("hidden");
  el("record-area").classList.remove("hidden");
}

async function sendCheer() {
  if (!blob) return;
  const sendBtn = el("send-btn");
  sendBtn.disabled = true;
  sendBtn.textContent = "Sending…";

  let cheerType = "anytime";
  let target = null;
  if (pendingCheer) {
    cheerType = pendingCheer.cheer_type;
    target = pendingCheer.target;
  } else {
    const when = el("when-select").value;
    if (when.includes(":")) [cheerType, target] = when.split(":");
  }

  const form = new FormData();
  form.append("file", blob, mode === "video" ? "cheer.webm" : "cheer.webm");
  form.append("media_type", mode);
  form.append("duration_seconds", String(elapsed));
  form.append("cheer_type", cheerType);
  if (target) form.append("target", target);
  if (mode === "voice_photo" && photoBlob) form.append("photo", photoBlob, "photo.jpg");

  try {
    const res = await fetch(`/api/cheer/upload/${token}`, { method: "POST", body: form });
    if (!res.ok) throw new Error("upload failed");
    const result = await res.json();
    ctx.sent_count = result.sent_count ?? ctx.sent_count + 1;
    showSent();
  } catch {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send";
    el("cheer-sub").textContent = "Something went wrong sending that. Please try again.";
  }
}

function showSent() {
  const n = ctx.sent_count;
  el("sent-progress").textContent = `${n} of ${ctx.goal} sent`;
  if (n < ctx.goal) {
    el("sent-note").textContent = `${n} of ${ctx.goal}! ${called} is going to love these.`;
  } else if (n === ctx.goal) {
    el("sent-note").textContent = `Thank you for all ${ctx.goal}! Feel free to keep sending more anytime.`;
  } else {
    el("sent-note").textContent = `Another one sent -- they'll love it!`;
  }
  show("sent");
}

init();
