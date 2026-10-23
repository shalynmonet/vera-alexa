// Exercises the real browser module (web/static/js/polly.js) under Node,
// with fakes standing in for fetch/Audio/AudioContext -- see
// tests/test_polly_stop.py, which runs this as a subprocess. The bug:
// stopPolly() used to just .pause() the <audio> element and abandon it,
// but .pause() alone never fires onended -- so the in-flight speakPolly()
// promise (and everything awaiting it, e.g. say()'s own cleanup that
// resets veraSpeaking) hung forever the moment anything stopped her
// mid-sentence, which a mic tap now routinely does.
import assert from "node:assert/strict";

globalThis.window = globalThis;

class FakeAudio {
  constructor(url) {
    this.url = url;
    this.onplay = null;
    this.onended = null;
    this.onerror = null;
    this.paused = true;
    FakeAudio.instances.push(this);
  }
  play() {
    this.paused = false;
    queueMicrotask(() => this.onplay?.());
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
  }
}
FakeAudio.instances = [];
window.Audio = FakeAudio;

class FakeAudioContext {
  constructor() { this.state = "running"; }
  resume() { this.state = "running"; return Promise.resolve(); }
  createMediaElementSource() { return { connect() {} }; }
  createAnalyser() { return { fftSize: 0, frequencyBinCount: 8, connect() {}, getByteFrequencyData: (arr) => arr.fill(0) }; }
  get destination() { return {}; }
}
window.AudioContext = FakeAudioContext;

// A no-op is enough here: the loop this drives (lip-sync sampling) isn't
// what's under test, and a real recursive rAF would just spin forever
// under Node with nothing ever pausing it.
window.requestAnimationFrame = () => 0;
window.cancelAnimationFrame = () => {};

window.fetch = async () => ({ ok: true, json: async () => ({ url: "https://example.com/fake.mp3" }) });

const { speakPolly, stopPolly } = await import("../web/static/js/polly.js");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const latestAudio = () => FakeAudio.instances.at(-1);

// stopPolly() must resolve the in-flight promise (not hang forever) and
// still fire onEnd/onMouthClosed, same as a natural end would.
{
  let ended = false;
  let mouthClosed = false;
  const p = speakPolly("hello", {
    onEnd: () => { ended = true; },
    onMouthClosed: () => { mouthClosed = true; },
  });
  await sleep(10); // let the fake fetch + onplay microtasks settle
  stopPolly();
  await p; // hangs the whole test (and its timeout) if this regresses
  assert.equal(ended, true, "onEnd should fire when stopped early, not just on a natural end");
  assert.equal(mouthClosed, true);
}

// Starting a new speakPolly() call while a previous one is still playing
// must resolve that previous one's promise too, not just abandon it.
{
  let firstEnded = false;
  const first = speakPolly("first", { onEnd: () => { firstEnded = true; } });
  await sleep(10);
  const second = speakPolly("second", {});
  await first; // must not hang
  assert.equal(firstEnded, true);
  stopPolly();
  await second;
}

// Natural completion (the audio element's own onended) still resolves
// normally -- the fix shouldn't break the ordinary, un-interrupted path.
{
  let ended = false;
  const p = speakPolly("third", { onEnd: () => { ended = true; } });
  await sleep(10);
  latestAudio().onended?.();
  await p;
  assert.equal(ended, true);
}

// stopPolly() with nothing playing is a harmless no-op.
{
  stopPolly();
}

console.log("polly stop: all checks passed");
