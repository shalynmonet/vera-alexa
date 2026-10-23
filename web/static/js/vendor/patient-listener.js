// Vendored from https://github.com/shalynmonet/patient-listener, tag v1.0.0
// -- update this file (and the tag noted here) together if it changes.
//
// patient-listener: a continuous speech-capture helper for the Web Speech
// API that decides for itself when someone is done talking, instead of
// handing back whatever the browser's own recognizer happened to catch
// before its first pause-triggered stop. Zero dependencies.
//
// Why this exists: SpeechRecognition's own "stop on pause" behavior is
// tuned for quick commands, not conversation. Anyone who speaks slowly,
// pauses to think, or has a tremor or breathing condition that puts gaps
// between words gets cut off mid-sentence -- and on iOS Safari specifically,
// results are often never marked `isFinal` at all, so a naive integration
// silently loses speech the person watched appear correctly on screen.
// This library fixes both: it keeps listening through natural pauses up to
// a configurable silence timeout, auto-restarts the recognizer when the
// browser ends a session on its own without losing the transcript so far,
// and falls back to the last text actually displayed when the browser
// never finalizes anything.

/** How long to wait with no new speech before deciding the person is done. */
export const DEFAULT_SILENCE_MS = 3000;

/** True if this browser exposes any form of SpeechRecognition. */
export function isSupported() {
  return typeof window !== "undefined" && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

/**
 * Start a continuous, restart-on-its-own speech capture session.
 *
 * @param {Object} [options]
 * @param {(text: string) => void} [options.onInterim] - called with the
 *   best transcript so far every time the recognizer reports new speech,
 *   final or not -- use this to render a live, updating transcript.
 * @param {number} [options.silenceMs] - how long to wait with no new
 *   speech before finishing on its own. Defaults to DEFAULT_SILENCE_MS.
 * @param {string} [options.lang] - BCP-47 language tag. Defaults to "en-US".
 *
 * @returns {{promise: Promise<string|null>, stop: () => void, cancel: () => void, cancelled: boolean}}
 *   `promise` resolves with the best transcript captured (a trimmed,
 *   non-empty string): the recognizer's own final result if it ever
 *   actually marked anything `isFinal`, otherwise the last text that was
 *   shown as the live interim transcript -- iOS Safari's
 *   webkitSpeechRecognition in continuous mode often never sets `isFinal`
 *   at all, so insisting on a final result there means losing speech the
 *   person watched appear correctly on screen. Resolves `null` only if
 *   nothing was ever displayed, recognition isn't supported, or `cancel()`
 *   was called.
 *   `stop()` finalizes immediately, resolving with whatever was captured
 *   so far (an explicit "I'm done talking" action).
 *   `cancel()` discards everything and resolves with `null`.
 *   `cancelled` becomes `true` once `cancel()` has been called, so a
 *   caller can distinguish "nothing was said" from "the user backed out".
 *
 * Known limitation: if the browser's own session boundary lands
 * mid-word, any not-yet-finalized interim text from that instant is lost
 * (the Web Speech API gives no way to recover an interim result after its
 * session ends) -- rare, and still strictly better than the default
 * cut-off-at-first-pause behavior, but not perfect.
 */
export function startListening({ onInterim, silenceMs = DEFAULT_SILENCE_MS, lang = "en-US" } = {}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const controller = { cancelled: false };
  if (!SR) {
    controller.promise = Promise.resolve(null);
    controller.stop = () => {};
    controller.cancel = () => { controller.cancelled = true; };
    return controller;
  }

  let finalTranscript = "";
  // The fullest text actually shown on screen so far -- survives a
  // browser-triggered session restart (these live in startListening's own
  // closure, not startSession's, so an onend-triggered restart below never
  // resets them) and is the fallback resolve value when finalTranscript
  // never got anything (the iOS case this fixes).
  let lastDisplayedText = "";
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
    const text = finalTranscript.trim() || lastDisplayedText.trim();
    resolvePromise(controller.cancelled ? null : (text || null));
  }

  function startSession() {
    rec = new SR();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (e) => {
      let finalPiece = "";
      // Not +=: some browsers (notably iOS Safari) reissue results
      // cumulatively -- each new one repeats the words from the last, with
      // whatever's newly been heard tacked on -- so concatenating every
      // non-final result in range would double up the same words over and
      // over. Only the latest one in this batch is ever the full-so-far
      // interim text, final or not.
      let latestInterim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const transcript = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalPiece += `${transcript} `;
        else latestInterim = transcript;
      }
      if (finalPiece) finalTranscript += finalPiece;
      const displayed = (finalTranscript + latestInterim).trim();
      if (displayed) lastDisplayedText = displayed;
      onInterim?.(displayed);
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
