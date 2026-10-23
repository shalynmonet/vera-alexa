// Fetches Vera's lines from the server (Amazon Polly, cached there) and
// plays them back with a Web Audio analyser driving real mouth-open/closed
// callbacks from the actual playback volume -- true lip sync, instead of a
// fixed timer. Throws on any failure so voice.js can fall back to the
// browser's own speech synthesis.

let audioCtx = null;
let currentAudio = null;
let currentStop = null; // () => void -- properly settles the in-flight speakPolly() promise; see stopPolly()

export function pollySupported() {
  return !!(window.AudioContext || window.webkitAudioContext);
}

function ensureContext() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
  }
  if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
  return audioCtx;
}

export async function speakPolly(text, { onMouthOpen, onMouthClosed, onStart, onEnd } = {}) {
  const res = await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`Polly request failed (${res.status})`);
  const { url } = await res.json();

  // Same reasoning as stopPolly(): settle any still-in-flight previous
  // playback's promise properly (fires its onEnd, resolves it) instead of
  // just pausing the element and abandoning it mid-promise.
  stopPolly();

  const ctx = ensureContext();
  const audio = new Audio(url);
  currentAudio = audio;

  const source = ctx.createMediaElementSource(audio);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);
  analyser.connect(ctx.destination);

  const data = new Uint8Array(analyser.frequencyBinCount);
  const MOUTH_OPEN_THRESHOLD = 12; // average byte amplitude (0-255)
  let raf = null;
  let open = false;

  function sampleVolume() {
    analyser.getByteFrequencyData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i];
    const avg = sum / data.length;
    const shouldOpen = avg > MOUTH_OPEN_THRESHOLD;
    if (shouldOpen !== open) {
      open = shouldOpen;
      (open ? onMouthOpen : onMouthClosed)?.();
    }
    raf = requestAnimationFrame(sampleVolume);
  }

  return new Promise((resolve, reject) => {
    const cleanup = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = null;
      if (currentAudio === audio) currentAudio = null;
      if (currentStop === stopThis) currentStop = null;
    };
    // stopPolly() calling this (instead of pausing the element directly
    // and abandoning the promise) is what matters: .pause() alone never
    // fires onended, so without this, every caller's `await
    // speakText(...)` -- and everything chained after it, e.g. say()'s
    // own finally block that resets veraSpeaking -- hung forever the
    // moment anything stopped her mid-sentence, silently breaking every
    // reply after.
    const stopThis = () => {
      cleanup();
      audio.pause();
      onMouthClosed?.();
      onEnd?.();
      resolve();
    };
    currentStop = stopThis;
    audio.onplay = () => {
      onStart?.();
      sampleVolume();
    };
    audio.onended = () => {
      cleanup();
      onMouthClosed?.();
      onEnd?.();
      resolve();
    };
    audio.onerror = () => {
      cleanup();
      onEnd?.();
      reject(new Error("Audio playback failed"));
    };
    audio.play().catch((e) => {
      cleanup();
      reject(e);
    });
  });
}

export function stopPolly() {
  currentStop?.();
}

export function pausePolly() {
  currentAudio?.pause();
}

export function resumePolly() {
  currentAudio?.play().catch(() => {});
}
