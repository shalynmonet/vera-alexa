import json

from vera import media


def test_enrich_marks_available_when_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(media, "EXERCISE_DIR", tmp_path / "exercise")
    media.EXERCISE_DIR.mkdir()
    (media.EXERCISE_DIR / "manifest.json").write_text(json.dumps([
        {"id": "a", "title": "A", "minutes": 5, "file": "a.mp4", "thumbnail": "a.jpg", "steps": []},
        {"id": "b", "title": "B", "minutes": 5, "file": "b.mp4", "thumbnail": None, "steps": []},
    ]), encoding="utf-8")
    (media.EXERCISE_DIR / "a.mp4").write_bytes(b"fake video")

    routines = {r["id"]: r for r in media.exercise_routines()}
    assert routines["a"]["available"] is True
    assert routines["a"]["media_url"] == "/media/exercise/a.mp4"
    assert routines["b"]["available"] is False
    assert routines["b"]["media_url"] is None


def test_missing_manifest_returns_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(media, "EXERCISE_DIR", tmp_path / "exercise")
    assert media.exercise_routines() == []


def test_meditation_lookup_by_id(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(media, "MEDITATION_DIR", tmp_path / "meditations")
    media.MEDITATION_DIR.mkdir()
    (media.MEDITATION_DIR / "manifest.json").write_text(json.dumps([
        {"id": "calm", "title": "Calm", "minutes": 3, "type": "audio", "file": "calm.m4a", "thumbnail": None, "intro": "Breathe."},
    ]), encoding="utf-8")
    (media.MEDITATION_DIR / "calm.m4a").write_bytes(b"fake audio")

    found = media.meditation("calm")
    assert found["available"] is True
    assert found["media_url"] == "/media/meditations/calm.m4a"
    assert media.meditation("missing") is None
