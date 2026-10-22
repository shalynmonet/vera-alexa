// Exercises the real browser module (web/static/js/chat-chips.js) under
// Node -- see tests/test_chat_chips.py, which runs this as a subprocess so
// the check is against the actual code the Chat screen uses, not a
// reimplementation of it in Python.
import assert from "node:assert/strict";
import { CHAT_DEFAULT_CHIPS, memoryChipText, buildChatChips, nextReplacementChip } from "../web/static/js/chat-chips.js";

// No memories: all five default chips, untouched.
{
  const { chips, memoryReserve } = buildChatChips([]);
  assert.deepEqual(chips, CHAT_DEFAULT_CHIPS);
  assert.deepEqual(memoryReserve, []);
}

// One memory personalizes exactly one of the five slots; the other four
// stay the original default chips.
{
  const { chips } = buildChatChips([{ fact: "She loves her garden" }]);
  assert.equal(chips.length, 5);
  assert.ok(chips.includes("She loves her garden"));
  const stillDefault = chips.filter((c) => CHAT_DEFAULT_CHIPS.includes(c));
  assert.equal(stillDefault.length, 4);
}

// Two memories personalize exactly two slots -- never more than two, even
// with a third memory available; the rest go to the reserve.
{
  const memories = [
    { fact: "She loves her garden" },
    { fact: "Destiny's volleyball game" },
    { fact: "A third memory to keep in reserve" },
  ];
  const { chips, memoryReserve } = buildChatChips(memories);
  const personalizedShown = chips.filter((c) => !CHAT_DEFAULT_CHIPS.includes(c));
  assert.equal(personalizedShown.length, 2);
  assert.deepEqual(memoryReserve, ["A third memory to keep in reserve"]);
}

// Using up a personalized chip pulls the next one from the memory reserve
// before falling back to a default -- it shouldn't go generic while
// there's still something personal left to offer.
{
  const memories = [
    { fact: "She loves her garden" },
    { fact: "Destiny's volleyball game" },
    { fact: "A memory kept in reserve" },
  ];
  const built = buildChatChips(memories);
  const state = { memoryReserve: built.memoryReserve, defaultCursor: built.defaultCursor };
  assert.equal(nextReplacementChip(state), "A memory kept in reserve");
  assert.deepEqual(state.memoryReserve, []);
}

// Once memories run out, replacements fall back to (and cycle through)
// the defaults rather than ever leaving a slot empty.
{
  const state = { memoryReserve: [], defaultCursor: 0 };
  for (let i = 0; i < CHAT_DEFAULT_CHIPS.length + 2; i++) {
    assert.ok(CHAT_DEFAULT_CHIPS.includes(nextReplacementChip(state)));
  }
}

// A long fact is shortened to fit the chip; a short one is shown as-is.
{
  const long = "This is a very long personal memory fact that definitely runs past the chip's comfortable display length";
  const short = memoryChipText(long);
  assert.ok(short.length <= 40);
  assert.ok(short.endsWith("…"));
  assert.equal(memoryChipText("Her garden."), "Her garden");
}

console.log("chat-chips: all checks passed");
