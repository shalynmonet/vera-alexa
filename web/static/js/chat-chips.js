// Pure chip-selection logic for the Chat screen's starter chips -- no DOM,
// so main.js can drive the UI with it and tests/test_chat_chips.py can
// exercise it directly under Node. Up to two of the five slots personalize
// from recent memories (most recent first, as get_memories returns them);
// the rest, and whatever replaces a used chip, come from a small set of
// default conversation starters.

export const CHAT_DEFAULT_CHIPS = [
  "Tell me a story",
  "Let's talk about the old days",
  "Tell me something that will make me smile",
  "What should we do next?",
  "Tell me a fun fact from history",
];

const CHIP_MAX_CHARS = 40;

export function memoryChipText(fact) {
  const trimmed = fact.trim().replace(/\.+$/, "");
  return trimmed.length > CHIP_MAX_CHARS ? `${trimmed.slice(0, CHIP_MAX_CHARS - 1).trimEnd()}…` : trimmed;
}

// Builds the initial 5 chips (up to 2 personalized from `memories`) plus a
// reserve to refill slots as they're used -- remaining memories first, so
// a used personalized chip is replaced by another personal one rather than
// going straight to a generic default while there's still something
// personal left to offer.
export function buildChatChips(memories) {
  const personalized = memories.slice(0, 2).map((m) => memoryChipText(m.fact));
  const memoryReserve = memories.slice(2).map((m) => memoryChipText(m.fact));
  const defaultCount = CHAT_DEFAULT_CHIPS.length - personalized.length;
  const chips = [...CHAT_DEFAULT_CHIPS.slice(0, defaultCount), ...personalized];
  return { chips, memoryReserve, defaultCursor: defaultCount };
}

// What should replace a chip slot that was just used: an unused memory
// first, falling back to defaults (cycling back through them rather than
// ever leaving a slot empty) once memories run out. Mutates `state`
// ({memoryReserve, defaultCursor}) in place.
export function nextReplacementChip(state) {
  if (state.memoryReserve.length) return state.memoryReserve.shift();
  const chip = CHAT_DEFAULT_CHIPS[state.defaultCursor % CHAT_DEFAULT_CHIPS.length];
  state.defaultCursor += 1;
  return chip;
}
