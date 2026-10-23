"""vera/media_convert.py -- converting an uploaded cheer recording to one
universal format and measuring its real duration with ffmpeg/ffprobe.
Skipped outright when ffmpeg isn't installed, same as the feature itself
gracefully degrades (see web/app.py's _prepare_cheer_media)."""
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from vera import media_convert

pytestmark = pytest.mark.skipif(not media_convert.available(), reason="ffmpeg/ffprobe not installed")


def _make_wav(path: Path, seconds: float, framerate: int = 8000) -> None:
    n = int(framerate * seconds)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(framerate)
        frames = bytearray()
        for i in range(n):
            sample = int(3000 * math.sin(2 * math.pi * 440 * i / framerate))
            frames += struct.pack("<h", sample)
        f.writeframes(bytes(frames))


def _make_mp4(path: Path, seconds: float) -> None:
    """A tiny H.264/AAC .mp4, standing in for what an iPhone's
    MediaRecorder would actually produce."""
    subprocess.run(
        [
            media_convert.FFMPEG, "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=15",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True, capture_output=True, timeout=30,
    )


def test_available_is_true_in_this_dev_environment():
    # If this fails, ffmpeg genuinely isn't on PATH here -- every other
    # test in this file is skipped by the module-level pytestmark, this
    # one just makes that visible instead of a silent "0 ran".
    assert media_convert.available()


def test_probe_duration_matches_a_known_length_audio_file(tmp_path):
    wav = tmp_path / "src.wav"
    _make_wav(wav, 2.5)
    assert media_convert.probe_duration(wav) == pytest.approx(2.5, abs=0.2)


def test_probe_duration_raises_for_a_file_that_isnt_media(tmp_path):
    junk = tmp_path / "not_media.wav"
    junk.write_bytes(b"this is not an audio file at all")
    with pytest.raises(media_convert.ConversionError):
        media_convert.probe_duration(junk)


def test_convert_audio_to_universal_m4a(tmp_path):
    src = tmp_path / "src.wav"
    _make_wav(src, 3)
    dest = tmp_path / "out.m4a"

    media_convert.convert_to_universal(src, dest, is_video=False)

    assert dest.exists() and dest.stat().st_size > 0
    assert media_convert.probe_duration(dest) == pytest.approx(3, abs=0.3)


def test_convert_video_to_universal_mp4_with_h264_and_aac(tmp_path):
    src = tmp_path / "src.mp4"
    _make_mp4(src, 2)
    dest = tmp_path / "out.mp4"

    media_convert.convert_to_universal(src, dest, is_video=True)

    assert dest.exists() and dest.stat().st_size > 0
    assert media_convert.probe_duration(dest) == pytest.approx(2, abs=0.3)

    probe = subprocess.run(
        [media_convert.FFPROBE, "-v", "error", "-show_entries", "stream=codec_name,codec_type",
         "-of", "default=noprint_wrappers=1", str(dest)],
        capture_output=True, text=True, timeout=30,
    )
    assert "codec_name=h264" in probe.stdout
    assert "codec_name=aac" in probe.stdout


def test_convert_raises_a_conversion_error_for_garbage_input(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not actually a video")
    dest = tmp_path / "out.mp4"
    with pytest.raises(media_convert.ConversionError):
        media_convert.convert_to_universal(junk, dest, is_video=True)


def test_probe_and_convert_raise_cleanly_when_tools_are_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(media_convert, "FFPROBE", None)
    monkeypatch.setattr(media_convert, "FFMPEG", None)
    assert media_convert.available() is False
    with pytest.raises(media_convert.ConversionError):
        media_convert.probe_duration(tmp_path / "whatever.wav")
    with pytest.raises(media_convert.ConversionError):
        media_convert.convert_to_universal(tmp_path / "a.wav", tmp_path / "b.m4a", is_video=False)
