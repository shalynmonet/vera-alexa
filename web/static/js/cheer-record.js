// Family Cheers: a family member's private, no-login record page. Standalone
// -- not part of the main Vera app's screen router, speech pipeline, or
// companion. Plain browser MediaRecorder, 30 second max, preview/re-record/send.

const MAX_SECONDS = 30;
const token = window.location.pathname.split("/").filter(Boolean).pop();
const presetMilestone = new URLSearchParams(window.location.search).get("milestone");

const el = (id) => document.getElementById(id);

let mode = null; // "audio" | "video"
let stream = null;
let recorder = null;
let chunks = [];
let blob = null;
let timerInterval = null;
let elapsed = 0;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function init() {
  let ctx;
  try {
    const qs = presetMilestone ? `?milestone=${encodeURIComponent(presetMilestone)}` : "";
    const res = await fetch(`/api/cheer/context/${token}${qs}`);
    ctx = await res.json();
  } catch {
    ctx = { valid: false };
  }

  el("loading").classList.add("hidden");
  if (!ctx.valid) {
    el("invalid").classList.remove("hidden");
    return;
  }

  el("recorder").classList.remove("hidden");
  el("cheer-title").textContent = `Record a cheer for ${ctx.recipient_name}`;
  el("cheer-sub").textContent =
    `Hi ${ctx.family_name}! Record a short message (up to 30 seconds) -- `
    + `Vera will play it for ${ctx.recipient_name} at just the right moment.`;

  const select = el("milestone-select");
  const options = [`<option value="">Anytime (saved for later)</option>`]
    .concat((ctx.upcoming_milestones || []).map((m) =>
      `<option value="${escapeHtml(m.id)}">${escapeHtml(m.title)} (${escapeHtml(m.distance_label)})</option>`
    ));
  select.innerHTML = options.join("");
  if (ctx.default_milestone_id) select.value = ctx.default_milestone_id;
  el("milestone-row").classList.remove("hidden");

  el("mode-audio-btn").addEventListener("click", () => chooseMode("audio"));
  el("mode-video-btn").addEventListener("click", () => chooseMode("video"));
  el("start-btn").addEventListener("click", startRecording);
  el("stop-btn").addEventListener("click", stopRecording);
  el("rerecord-btn").addEventListener("click", resetRecording);
  el("send-btn").addEventListener("click", sendCheer);
}

async function chooseMode(m) {
  mode = m;
  el("mode-row").classList.add("hidden");
  el("record-area").classList.remove("hidden");
  try {
    stream = await navigator.mediaDevices.getUserMedia(
      m === "video" ? { audio: true, video: true } : { audio: true }
    );
  } catch {
    el("cheer-sub").textContent = "Vera couldn't access your microphone or camera. Please allow access and reload the page.";
    return;
  }
  if (m === "video") {
    const v = el("preview-video");
    v.srcObject = stream;
    v.classList.remove("hidden");
    v.play().catch(() => {});
  }
}

function renderTimer() {
  el("timer").textContent = `0:${String(elapsed).padStart(2, "0")} / 0:${MAX_SECONDS}`;
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
  el("record-area").classList.add("hidden");
  el("preview-area").classList.remove("hidden");
  const url = URL.createObjectURL(blob);
  if (mode === "video") {
    const v = el("playback-video");
    v.src = url;
    v.classList.remove("hidden");
  } else {
    const a = el("playback-audio");
    a.src = url;
    a.classList.remove("hidden");
  }
}

function resetRecording() {
  blob = null;
  el("playback-video").classList.add("hidden");
  el("playback-audio").classList.add("hidden");
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

  const form = new FormData();
  form.append("file", blob, "cheer.webm");
  form.append("media_type", mode);
  const milestoneId = el("milestone-select").value;
  if (milestoneId) form.append("milestone_id", milestoneId);

  try {
    const res = await fetch(`/api/cheer/upload/${token}`, { method: "POST", body: form });
    if (!res.ok) throw new Error("upload failed");
    el("preview-area").classList.add("hidden");
    el("sent").classList.remove("hidden");
  } catch {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send";
    el("cheer-sub").textContent = "Something went wrong sending that. Please try again.";
  }
}

init();
