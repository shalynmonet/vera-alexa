// Thin wrappers around the browser's Web Speech APIs (SpeechSynthesis for
// Vera's voice, SpeechRecognition for listening). Both degrade gracefully:
// speak() resolves immediately if unsupported, startListening()'s promise
// resolves to null so callers always fall back to the type-to-talk box.

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
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

// How long to wait with no new speech before deciding she's finished talking.
// The single place this is configured, per the "one config setting" ask.
export const SILENCE_MS = 3000;

// Continuous speech capture that decides for itself when the person is done
// talking, instead of handing back whatever the browser's own recognizer
// happened to catch before its first pause-triggered stop. Chrome (even
// with continuous=true) still ends a recognition session on its own after a
// pause or about a minute -- when that happens here, and we haven't decided
// she's finished, the same recognizer is simply restarted and keeps
// appending to the same running transcript, so from the caller's
// perspective listening never stops until WE say so: either `silenceMs`
// with nothing new, or the caller calling stop()/cancel().
//
// Known limitation: if Chrome's own session boundary lands mid-word, any
// not-yet-finalized interim text from that instant is lost (the Web Speech
// API gives no way to recover an interim result after its session ends) --
// rare, and still strictly better than the old cut-off-at-first-pause
// behavior, but not perfect.
//
// Returns a controller: { promise, stop, cancel, cancelled }.
//   promise  resolves with the final transcript (a trimmed, non-empty
//            string), or null if nothing was said, recognition isn't
//            supported, or cancel() was called.
//   stop()   finalizes now, resolving with whatever was captured so far
//            (the "I'm done talking" button).
//   cancel() discards everything and resolves with null (tap-the-mic-again).
//   cancelled  true once cancel() has been called -- lets the caller skip
//              an "I didn't catch that" message after an intentional cancel.
export function startListening({ onInterim, silenceMs = SILENCE_MS } = {}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const controller = { cancelled: false };
  if (!SR) {
    controller.promise = Promise.resolve(null);
    controller.stop = () => {};
    controller.cancel = () => { controller.cancelled = true; };
    return controller;
  }

  let finalTranscript = "";
  let silenceTimer = null;
  let finished = false;
  let rec = null;
  let resolvePromise;
  controller.promise = new Promise((resolve) => { resolvePromise = resolve; });

  function resetSilenceTimer() {
    clearTimeout(silenceTimer);
    silenceTimer = setTimeout(finish, silenceMs);
  }

  function finish() {
    if (finished) return;
    finished = true;
    clearTimeout(silenceTimer);
    if (rec) {
      rec.onend = null; // this was a deliberate stop -- don't auto-restart
      try { rec.stop(); } catch { /* already stopped */ }
    }
    const text = finalTranscript.trim();
    resolvePromise(controller.cancelled ? null : (text || null));
  }

  function startSession() {
    rec = new SR();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const transcript = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalTranscript += `${transcript} `;
        else interim += transcript;
      }
      onInterim?.((finalTranscript + interim).trim());
      resetSilenceTimer();
    };
    rec.onerror = (e) => {
      // "no-speech" / "aborted" are routine in continuous mode -- onend
      // follows right after and restarts things below. A real permission
      // problem is the one case worth giving up on.
      if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "audio-capture") {
        finish();
      }
    };
    rec.onend = () => {
      if (finished) return;
      try {
        rec.start();
      } catch {
        // Starting immediately after onend occasionally throws -- give the
        // browser a beat and try once more rather than silently going deaf.
        setTimeout(() => {
          if (finished) return;
          try { rec.start(); } catch { finish(); }
        }, 250);
      }
    };
    try {
      rec.start();
    } catch {
      finish();
    }
  }

  resetSilenceTimer();
  startSession();

  controller.stop = finish;
  controller.cancel = () => {
    controller.cancelled = true;
    finish();
  };
  return controller;
}
