// Thin wrappers around the browser's Web Speech APIs (SpeechSynthesis for
// Vera's voice, SpeechRecognition for listening). Both degrade gracefully:
// speak() resolves immediately if unsupported, listen() resolves to null so
// callers always fall back to the type-to-talk box.

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

function pickVoice(voices) {
  return (
    voices.find((v) => v.lang?.startsWith("en") && /aria|jenny|samantha|female/i.test(v.name)) ||
    voices.find((v) => v.lang?.startsWith("en-US")) ||
    voices.find((v) => v.lang?.startsWith("en")) ||
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
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export function listen({ onStart, onEnd, timeoutMs = 8000 } = {}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return Promise.resolve(null);
  return new Promise((resolve) => {
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      onEnd?.();
      resolve(value);
    };
    rec.onstart = () => onStart?.();
    rec.onresult = (e) => finish(e.results[0][0].transcript);
    rec.onerror = () => finish(null);
    rec.onend = () => finish(null);
    const timer = setTimeout(() => {
      try { rec.stop(); } catch { /* already stopped */ }
    }, timeoutMs);
    try {
      rec.start();
    } catch {
      finish(null);
    }
  });
}
