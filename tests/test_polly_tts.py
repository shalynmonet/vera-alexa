from web import polly_tts


def test_cache_key_deterministic():
    assert polly_tts._cache_key("hello") == polly_tts._cache_key("hello")


def test_cache_key_differs_by_text():
    assert polly_tts._cache_key("hello") != polly_tts._cache_key("goodbye")


def test_synthesize_returns_cached_file_without_calling_polly(tmp_path, monkeypatch):
    monkeypatch.setattr(polly_tts, "CACHE_DIR", tmp_path)
    filename = f"{polly_tts._cache_key('hi there')}.mp3"
    (tmp_path / filename).write_bytes(b"fake audio")

    def boom():
        raise AssertionError("Polly should not be called for a cache hit")
    monkeypatch.setattr(polly_tts, "_polly", boom)

    assert polly_tts.synthesize("hi there") == filename
