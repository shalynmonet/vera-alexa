"""Personal-fact memories Vera can recall later in conversation -- family,
hobbies, upcoming events. Health details are refused here as a backstop to
the system prompt instruction never to ask for or save them.
"""
from __future__ import annotations

MAX_MEMORIES = 100

# Conservative keyword backstop. Not exhaustive -- the real guardrail is the
# Bedrock system prompt telling Nova never to call remember_fact with health
# details in the first place; this just catches the obvious cases too.
_HEALTH_WORDS = [
    "diagnos", "medication", "medicine", "prescription", "doctor", "symptom",
    "surgery", "cancer", "blood pressure", "diabetes", "hospital", "therapy",
    "mental health", "depress", "anxiety", "disease", "illness", "pain",
    "dementia", "alzheimer", "health condition", "nurse", "physical therapy",
]


def is_health_related(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in _HEALTH_WORDS)


def add(memories: list[dict], fact: str, day_iso: str, category: str | None = None) -> dict:
    entry = {"fact": fact.strip(), "recorded_on": day_iso}
    if category:
        entry["category"] = category
    memories.append(entry)
    del memories[:-MAX_MEMORIES]
    return entry


def recent(memories: list[dict], limit: int) -> list[dict]:
    """Most recent first."""
    return list(reversed(memories[-limit:]))
