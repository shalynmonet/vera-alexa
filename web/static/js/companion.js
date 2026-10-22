// Vera's persistent on-screen companion: one DOM node that gets moved into
// whichever screen's "vera-slot" is active, with a pose image and speech
// bubble. Poses are plain images today. To upgrade a pose to a looping video
// later: add a `video` path alongside `img` in POSES and flip USE_VIDEO to
// true -- renderStage() is the only place that reads either field, so call
// sites like setPose()/say()/celebrate() never need to change.

const USE_VIDEO = false;

const POSES = {
  idle: { img: "/img/vera-idle.webp", video: "/media/vera-idle.mp4" },
  listening: { img: "/img/vera-listening.webp", video: "/media/vera-listening.mp4" },
  talking: { img: "/img/vera-talking.webp", video: "/media/vera-talking.mp4" },
  "talking-closed": { img: "/img/vera-talking-closed.webp", video: "/media/vera-talking-closed.mp4" },
  celebrating: { img: "/img/vera-celebrating.webp", video: "/media/vera-celebrating.mp4" },
  thinking: { img: "/img/vera-thinking.webp", video: "/media/vera-thinking.mp4" },
  exercising: { img: "/img/vera-exercising.webp", video: "/media/vera-exercising.mp4" },
  meditating: { img: "/img/vera-meditating.webp", video: "/media/vera-meditating.mp4" },
};

// Vera's default pose for each screen/section, per the Day 2 design spec.
const SECTION_POSE = {
  start: "idle",
  home: "idle",
  games: "thinking",
  memory: "thinking",
  matching: "thinking",
  saying: "thinking",
  category: "thinking",
  exercise: "exercising",
  stretch: "exercising",
  "log-activity": "exercising",
  "timed-activity": "exercising",
  meditation: "meditating",
  progress: "celebrating",
  cheers: "celebrating",
  chat: "idle",
};

let root, img, bubble;
let baseScreen = "home";

function init() {
  root = document.getElementById("vera-companion");
  img = document.getElementById("vera-img");
  bubble = document.getElementById("vera-bubble");
}

function renderStage(poseName) {
  const pose = POSES[poseName] || POSES.idle;
  if (USE_VIDEO && pose.video) {
    // Swap `img` for a <video loop muted autoplay> here when real clips
    // land -- setPose/say/celebrate below keep working unchanged.
  }
  img.src = pose.img;
  img.alt = `Vera ${poseName.replace("-", " ")}`;
}

function setPose(poseName) {
  root.dataset.pose = poseName;
  renderStage(poseName);
}

function basePose() {
  return SECTION_POSE[baseScreen] || "idle";
}

// Move the companion into a screen's slot and show that section's pose.
function placeInScreen(screenName) {
  const slot = document.getElementById(`vera-slot-${screenName}`);
  if (!slot) return;
  baseScreen = screenName;
  slot.appendChild(root);
  root.dataset.size = slot.dataset.size || "corner";
  root.classList.remove("celebrate-pose");
  setPose(basePose());
}

function setVideoMode(on) {
  root.classList.toggle("video-mode", !!on);
}

function showBubble(text) {
  if (!text) {
    bubble.classList.add("hidden");
    bubble.textContent = "";
    return;
  }
  bubble.textContent = text;
  bubble.classList.remove("hidden");
}

// Mouth state while talking is driven from outside (real playback volume
// via Amazon Polly + a Web Audio analyser, or a timed approximation for the
// browser-speech fallback) -- see web/static/js/voice.js. This module just
// renders whichever frame it's told.
function setTalkingVisual(on) {
  root.classList.toggle("talking", !!on);
  if (!on) setPose(basePose());
}

function setMouthFrame(open) {
  renderStage(open ? "talking" : "talking-closed");
}

function setListening(on) {
  root.classList.toggle("listening", !!on);
  setPose(on ? "listening" : basePose());
}

// Speak through the caller's voice function, which receives
// {onMouthOpen, onMouthClosed} to drive the mouth frame while the bubble
// shows the words. main.js/voice.js own the actual audio; this module stays
// focused on the character.
async function say(text, speakFn) {
  showBubble(text);
  if (!text) return;
  setTalkingVisual(true);
  try {
    await speakFn({ onMouthOpen: () => setMouthFrame(true), onMouthClosed: () => setMouthFrame(false) });
  } finally {
    setTalkingVisual(false);
  }
}

async function celebrate(text, speakFn) {
  const overlaySlot = document.getElementById("vera-slot-celebrate");
  const previousScreen = baseScreen;
  overlaySlot.appendChild(root);
  root.dataset.size = "celebrate";
  root.classList.add("celebrate-pose");
  setPose("celebrating");
  showBubble(text);
  // No talking/talking-closed poses exist for the celebrate costume, so she
  // just stays in the celebrating pose (the CSS bounce still gives it life)
  // rather than flickering to a mismatched pose while speaking.
  await speakFn({});
  placeInScreen(previousScreen);
}

export const Companion = {
  init,
  placeInScreen,
  setVideoMode,
  setListening,
  say,
  celebrate,
  showBubble,
};
