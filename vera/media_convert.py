"""Converts an uploaded Family Cheer recording to one universal playable
format via ffmpeg, so a cheer recorded on an iPhone (Safari's MediaRecorder
produces audio/mp4 or video/mp4) plays back fine on Android (which prefers
webm) and vice versa, instead of showing a broken player for whoever's on
the "wrong" device. Also the one place a recording's real duration is
measured -- a client-reported value can be missing or wrong for an
uploaded file, so the 15 second cap is enforced against what ffprobe
actually measures.

Entirely optional, same "optional unless configured" pattern as
vera/cloud_storage.py and friends: when ffmpeg/ffprobe aren't on PATH,
`available()` is False and callers fall back to saving the upload as-is,
trusting the client-reported duration -- correctness over availability,
not the other way around, since a demo with no ffmpeg installed should
still work (as it always has), just without the cross-device guarantee.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# What every cheer becomes, regardless of what device/browser recorded it.
VIDEO_EXTENSION = "mp4"
AUDIO_EXTENSION = "m4a"

_PROBE_TIMEOUT = 30
_CONVERT_TIMEOUT = 60


class ConversionError(RuntimeError):
    pass


def available() -> bool:
    return bool(FFMPEG and FFPROBE)


def probe_duration(path: Path) -> float:
    """The file's real, decoded duration in seconds."""
    if not FFPROBE:
        raise ConversionError("ffprobe is not installed.")
    try:
        result = subprocess.run(
            [
                FFPROBE, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConversionError(f"Couldn't read that recording: {e}") from e
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        raise ConversionError(f"Couldn't read that recording's duration: {result.stderr.strip()}")
    try:
        return float(text)
    except ValueError as e:
        raise ConversionError("Couldn't read that recording's duration.") from e


def convert_to_universal(src: Path, dest: Path, is_video: bool) -> None:
    """Re-encodes src to dest in the one format every cheer is stored as:
    H.264 + AAC .mp4 with faststart for video, AAC .m4a for audio-only --
    picked for being the pair every mainstream phone/browser can both
    record something close to and play back natively."""
    if not FFMPEG:
        raise ConversionError("ffmpeg is not installed.")
    if is_video:
        args = [
            FFMPEG, "-y", "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-movflags", "+faststart",
            str(dest),
        ]
    else:
        args = [
            FFMPEG, "-y", "-i", str(src),
            "-vn", "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            str(dest),
        ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=_CONVERT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConversionError(f"Couldn't convert that recording: {e}") from e
    if result.returncode != 0 or not dest.exists():
        raise ConversionError(f"Couldn't convert that recording: {result.stderr.strip()[-800:]}")
