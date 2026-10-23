// Thin wrappers around the browser's Web Speech APIs (SpeechSynthesis for
// Vera's voice, SpeechRecognition for listening). Both degrade gracefully:
// speak() resolves immediately if unsupported, startListening()'s promise
// resolves to null so callers always fall back to the type-to-talk box.
//
// Listening itself is handled by patient-listener (./vendor/patient-listener.js),
// a standalone library extracted from this file: see
// https://github.com/shalynmonet/patient-listener

import { isSupported as patientListenerSupported } from "./vendor/patient-listener.js";

export { startListening } from "./vendor/patient-listener.js";

let voicesPromise = null;

function ensureVoices() {
  if (!("speechSynthesis" in window)) return Promise.resolve([]);
  if (voicesPromise) return voicesPromise;
  voicesPromise = new Promise((resolve) => {
    const existing = speechSynthesis.getVoices();
    if (existing.length) return resolve(existing);
    speechSynthesis.onvoiceschanged = () => resolve(speechSynthesis.getVoices());
    // Some browsers never fire the event if there simply are no voices yet.
    setTimeout(() => resolve(speechSynthesis.getVoices()), 1000);
  });
  return voicesPromise;
}

// The Web Speech API exposes no standard gender field, so this is a name
// heuristic covering common female voices across Windows, macOS/iOS, and
// Chrome/Android voice packs -- used only for the browser-speech fallback
// (Amazon Polly, Vera's primary voice, is explicitly set to Ruth).
const FEMALE_NAME_HINTS = /\bfemale\b|zira|jenny|aria(?!l)|samantha|victoria|karen|moira|tessa|fiona|ava|allison|susan|kathy|serena|salli|joanna|kendra|kimberly|ruth|ivy|danielle|hazel|libby|sonia|emma|olivia|amy|eva|michelle|princess/i;
const MALE_NAME_HINTS = /\bmale\b|matthew|david|mark|james|daniel|george|ryan|guy(?!ana)|justin|joey|kevin|stephen|brian|eric/i;

function pickVoice(voices) {
  const en = voices.filter((v) => v.lang?.toLowerCase().startsWith("en"));
  const pool = en.length ? en : voices;
  return (
    pool.find((v) => FEMALE_NAME_HINTS.test(v.name) && !MALE_NAME_HINTS.test(v.name)) ||
    pool.find((v) => v.lang?.startsWith("en-US")) ||
    pool[0] ||
    voices[0]
  );
}

export async function speak(text, { rate = 0.9, onStart, onEnd } = {}) {
  if (!text) return;
  if (!("speechSynthesis" in window)) {
    onStart?.();
    onEnd?.();
    return;
  }
  const voices = await ensureVoices();
  return new Promise((resolve) => {
    const utter = new SpeechSynthesisUtterance(text);
    const voice = pickVoice(voices);
    if (voice) utter.voice = voice;
    utter.rate = rate;
    utter.pitch = 1.0;
    utter.onstart = () => onStart?.();
    const finish = () => {
      onEnd?.();
      resolve();
    };
    utter.onend = finish;
    utter.onerror = finish;
    speechSynthesis.cancel(); // don't let lines queue up and overlap
    speechSynthesis.speak(utter);
  });
}

export function speechSynthesisSupported() {
  return "speechSynthesis" in window;
}

export function speechRecognitionSupported() {
  return patientListenerSupported();
}

// Listening itself -- accumulating across restarts, the silence-based
// "she's done talking" timer, the iOS fallback-to-displayed-text behavior,
// stop()/cancel() -- lives in patient-listener now (imported above); see
// that library's own docs for the full behavior and the controller shape
// (`{ promise, stop, cancel, cancelled }`) it returns.
