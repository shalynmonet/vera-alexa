from vera import memories


def test_is_health_related_detects_common_terms():
    assert memories.is_health_related("My doctor changed my medication")
    assert memories.is_health_related("I've had a lot of pain in my knee")
    assert not memories.is_health_related("My granddaughter has a volleyball game Saturday")


def test_add_and_recent_most_recent_first():
    mem = []
    memories.add(mem, "Loves gardening", "2026-01-01")
    memories.add(mem, "Granddaughter plays volleyball", "2026-01-02")
    recent = memories.recent(mem, 10)
    assert recent[0]["fact"] == "Granddaughter plays volleyball"
    assert recent[1]["fact"] == "Loves gardening"


def test_add_stores_category_when_given():
    mem = []
    entry = memories.add(mem, "Birthday next week", "2026-01-01", category="event")
    assert entry["category"] == "event"


def test_recent_respects_limit():
    mem = []
    for i in range(5):
        memories.add(mem, f"fact {i}", "2026-01-01")
    assert len(memories.recent(mem, 2)) == 2


def test_memories_capped_at_max():
    mem = []
    for i in range(memories.MAX_MEMORIES + 10):
        memories.add(mem, f"fact {i}", "2026-01-01")
    assert len(mem) == memories.MAX_MEMORIES
    assert mem[-1]["fact"] == f"fact {memories.MAX_MEMORIES + 9}"
