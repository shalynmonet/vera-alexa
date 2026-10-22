// Exercises the real browser module (web/static/js/speech.js) under Node,
// with a fake SpeechRecognition standing in for the browser's -- see
// tests/test_speech_listening.py, which runs this as a subprocess. There's
// no real microphone here, but the whole point of the robustness fix is
// app-level logic (accumulate across a forced restart, decide "done" by
// silence rather than the browser's own pause-triggered stop, cancel/stop
// semantics), and that logic is exactly what this drives directly.
import assert from "node:assert/strict";

globalThis.window = globalThis;

// A SpeechRecognitionResult is array-like: indexable to alternatives, with
// an .isFinal flag -- this builds one the same shape the real API gives.
function mkResult(transcript, isFinal) {
  const r = [{ transcript }];
  r.isFinal = isFinal;
  return r;
}

class FakeRecognition {
  constructor() {
    this.results = [];
    this.started = false;
    this.onresult = null;
    this.onerror = null;
    this.onend = null;
    FakeRecognition.instances.push(this);
  }
  start() {
    if (this.started) throw new Error("InvalidStateError: recognition already started");
    this.started = true;
    this.results = []; // a new session starts its own fresh results list, like a real browser
  }
  stop() {
    this.started = false;
  }
  // Test helpers standing in for what a real browser fires as speech comes
  // in: updateInterim() refines the one in-progress (non-final) result,
  // finalize() locks the current result in as final -- both the way a
  // browser keeps revising the same trailing result until it's finalized.
  _setTrailing(transcript, isFinal) {
    const idx = this.results.length && !this.results[this.results.length - 1].isFinal
      ? this.results.length - 1
      : this.results.length;
    this.results[idx] = mkResult(transcript, isFinal);
    this.results.length = idx + 1;
    this.onresult?.({ resultIndex: idx, results: this.results });
  }
  updateInterim(transcript) { this._setTrailing(transcript, false); }
  finalize(transcript) { this._setTrailing(transcript, true); }
  triggerEnd() {
    this.started = false;
    this.onend?.();
  }
  triggerError(error) {
    this.onerror?.({ error });
  }
}
FakeRecognition.instances = [];

window.SpeechRecognition = FakeRecognition;

const { startListening } = await import("../web/static/js/speech.js");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const latestRec = () => FakeRecognition.instances.at(-1);

// A long sentence spread across several updates, with the browser forcibly
// ending the session mid-utterance (a pause, or Chrome's ~1 minute cap) --
// the same recognizer should restart on its own and the transcript should
// keep accumulating across that restart instead of losing everything after
// the cut.
{
  const ctrl = startListening({ silenceMs: 50 });
  const rec = latestRec();
  rec.updateInterim("hello there");
  rec.finalize("hello there, this is a long sentence");
  rec.triggerEnd();
  assert.ok(rec.started, "recognition should auto-restart after the browser ends the session on its own");
  rec.finalize("and it keeps going after the restart");
  await sleep(80); // let the silence timer elapse now that she's stopped talking
  const transcript = await ctrl.promise;
  assert.equal(transcript, "hello there, this is a long sentence and it keeps going after the restart");
}

// Each new word resets the silence timer -- it only finishes after a real
// gap with nothing new, not just after silenceMs has elapsed in total.
{
  const interims = [];
  const ctrl = startListening({ silenceMs: 60, onInterim: (t) => interims.push(t) });
  let resolved = false;
  ctrl.promise.then(() => { resolved = true; });
  const rec = latestRec();
  rec.updateInterim("one");
  await sleep(35);
  assert.equal(resolved, false, "should still be listening before silenceMs has elapsed");
  rec.updateInterim("one two"); // a new word -- resets the 60ms timer
  await sleep(35);
  assert.equal(resolved, false, "a new word should have reset the silence timer, not just continued the old one");
  await sleep(40); // now actually let 60ms pass with nothing new
  await ctrl.promise;
  assert.equal(resolved, true);
  assert.deepEqual(interims, ["one", "one two"]);
}

// cancel() discards everything and resolves null, regardless of what was
// captured -- "tap the mic again to cancel without sending".
{
  const ctrl = startListening({ silenceMs: 5000 });
  const rec = latestRec();
  rec.finalize("something was said");
  ctrl.cancel();
  const result = await ctrl.promise;
  assert.equal(result, null);
  assert.equal(ctrl.cancelled, true);
  assert.equal(rec.started, false, "cancel should stop the recognizer rather than leaving it running");
}

// stop() finalizes immediately with whatever was captured so far, without
// waiting for the silence timer -- the "I'm done talking" button.
{
  const ctrl = startListening({ silenceMs: 5000 });
  const rec = latestRec();
  rec.finalize("I went for a walk this morning");
  const raced = await Promise.race([ctrl.promise, sleep(30).then(() => "__still_listening__")]);
  assert.equal(raced, "__still_listening__", "shouldn't have finished yet -- silenceMs is long and stop() hasn't been called");
  ctrl.stop();
  const result = await ctrl.promise;
  assert.equal(result, "I went for a walk this morning");
  assert.equal(ctrl.cancelled, false);
}

// A real permission problem ends listening right away instead of retrying
// forever.
{
  const ctrl = startListening({ silenceMs: 5000 });
  const rec = latestRec();
  rec.triggerError("not-allowed");
  const result = await ctrl.promise;
  assert.equal(result, null);
}

// No SpeechRecognition in this browser at all -- resolves null immediately
// so the caller falls back to type-to-talk.
{
  const saved = window.SpeechRecognition;
  window.SpeechRecognition = undefined;
  const ctrl = startListening();
  const result = await ctrl.promise;
  assert.equal(result, null);
  window.SpeechRecognition = saved;
}

console.log("speech listening: all checks passed");
