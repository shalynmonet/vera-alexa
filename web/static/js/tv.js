// Living Room Display: a SIMULATED Fire TV, not a real device integration.
// Subscribes over server-sent events to whatever session (if any) the main
// screen has handed off via handoff_session_to_display, and mirrors it --
// the main screen is still what actually drives narration and timing.

const userId = window.location.pathname.split("/").filter(Boolean).pop();
const el = (id) => document.getElementById(id);

let currentCheerFile = null; // avoid re-triggering the same cheer on every tick

function renderState(state) {
  const session = state && state.session;
  el("tv-idle").classList.toggle("hidden", !!session);
  el("tv-session").classList.toggle("hidden", !session);
  if (!session) {
    hideCheer();
    return;
  }

  el("tv-title").textContent = session.title || "";
  el("tv-step").textContent = session.step_name || "";
  el("tv-step").classList.toggle("hidden", !session.step_name);
  el("tv-say").textContent = session.say || "";

  if (typeof session.progress_percent === "number") {
    el("tv-progress-track").classList.remove("hidden");
    el("tv-progress-fill").style.width = `${session.progress_percent}%`;
  } else {
    el("tv-progress-track").classList.add("hidden");
  }

  if (session.cheer && session.cheer.file !== currentCheerFile) {
    showCheer(session.cheer);
  } else if (!session.cheer) {
    hideCheer();
  }
}

function showCheer(cheer) {
  currentCheerFile = cheer.file;
  const overlay = el("tv-cheer-overlay");
  const photoEl = el("tv-cheer-photo");
  const videoEl = el("tv-cheer-video");
  const audioEl = el("tv-cheer-audio");
  const isVideo = cheer.media_type === "video";
  const hasPhoto = cheer.media_type === "voice_photo" && (cheer.photo_url || cheer.photo_file);

  el("tv-cheer-from").textContent = `A message from ${cheer.family_name}`;
  videoEl.classList.toggle("hidden", !isVideo);
  audioEl.classList.toggle("hidden", isVideo);
  photoEl.classList.toggle("hidden", !hasPhoto);
  if (hasPhoto) photoEl.src = cheer.photo_url || `/cheer-media/${cheer.photo_file}`;

  const mediaEl = isVideo ? videoEl : audioEl;
  mediaEl.src = cheer.url || `/cheer-media/${cheer.file}`;
  overlay.classList.remove("hidden");
  mediaEl.play().catch(() => {});
}

function hideCheer() {
  currentCheerFile = null;
  el("tv-cheer-overlay").classList.add("hidden");
  el("tv-cheer-video").pause();
  el("tv-cheer-audio").pause();
  el("tv-cheer-video").removeAttribute("src");
  el("tv-cheer-audio").removeAttribute("src");
}

const source = new EventSource(`/api/display/events/${userId}`);
source.onmessage = (e) => {
  try {
    renderState(JSON.parse(e.data));
  } catch {
    // malformed/keep-alive frame -- ignore
  }
};
source.onerror = () => {
  el("tv-idle-text").textContent = "Couldn't reach Vera's server. Reconnecting…";
};
