// How Vera speaks: Amazon Polly first (real lip sync from actual playback
// volume, see polly.js), falling back to the browser's own SpeechSynthesis
// -- with a timed mouth-flap approximation, since that API exposes no audio
// to analyse -- if Polly isn't configured or the request fails.

import { speak as browserSpeak } from "./speech.js";
import { speakPolly, pollySupported, stopPolly, pausePolly, resumePolly } from "./polly.js";

const FLAP_MS = 220;

async function speakWithFlap(text, { onMouthOpen, onMouthClosed, onStart, onEnd } = {}) {
  let open = true;
  onMouthOpen?.();
  const timer = setInterval(() => {
    open = !open;
    (open ? onMouthOpen : onMouthClosed)?.();
  }, FLAP_MS);
  try {
    await browserSpeak(text, { onStart, onEnd });
  } finally {
    clearInterval(timer);
    onMouthClosed?.();
  }
}

export async function speakText(text, callbacks = {}) {
  if (!text) return;
  if (pollySupported()) {
    try {
      await speakPolly(text, callbacks);
      return;
    } catch {
      // Polly not configured, no AWS permission, or a network hiccup --
      // the browser's own voice keeps the demo working either way.
    }
  }
  await speakWithFlap(text, callbacks);
}

// Stop/pause/resume whichever backend is currently speaking (Polly audio,
// browser SpeechSynthesis, or both -- harmless to call when idle).
export function stopSpeaking() {
  stopPolly();
  speechSynthesis.cancel();
}

export function pauseSpeaking() {
  pausePolly();
  speechSynthesis.pause();
}

export function resumeSpeaking() {
  resumePolly();
  speechSynthesis.resume();
}
