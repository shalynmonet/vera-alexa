"""Amazon Polly text-to-speech for Vera, with on-disk caching.

A warm neural voice, read slightly slower (SSML prosody) for older ears,
replaces the browser's own SpeechSynthesis as Vera's primary voice. Audio is
cached on disk by a hash of the text/voice/rate so repeated lines (greetings,
instructions) are synthesized once. If this fails for any reason -- no AWS
credentials, no Polly permission, network trouble -- the caller (the
frontend's voice.js) falls back to the browser's own speech synthesis.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from xml.sax.saxutils import escape

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
VOICE_ID = os.environ.get("VERA_POLLY_VOICE", "Joanna")
ENGINE = os.environ.get("VERA_POLLY_ENGINE", "neural")
RATE = os.environ.get("VERA_POLLY_RATE", "92%")  # slightly slower, for older ears

CACHE_DIR = Path(__file__).resolve().parent / "audio_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_client = None


def _polly():
    global _client
    if _client is None:
        _client = boto3.client("polly", region_name=REGION)
    return _client


class TTSError(RuntimeError):
    pass


def _cache_key(text: str) -> str:
    raw = f"{VOICE_ID}|{ENGINE}|{RATE}|{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def synthesize(text: str) -> str:
    """Return the audio_cache filename (mp3) for this text, synthesizing and
    caching it with Polly first if it isn't already cached. Raises TTSError
    on any Polly/AWS failure."""
    filename = f"{_cache_key(text)}.mp3"
    path = CACHE_DIR / filename
    if path.exists():
        return filename

    ssml = f'<speak><prosody rate="{RATE}">{escape(text)}</prosody></speak>'
    try:
        resp = _polly().synthesize_speech(
            Text=ssml,
            TextType="ssml",
            OutputFormat="mp3",
            VoiceId=VOICE_ID,
            Engine=ENGINE,
        )
    except (ClientError, BotoCoreError) as e:
        raise TTSError(str(e)) from e

    audio = resp["AudioStream"].read()
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(audio)
    tmp.replace(path)
    return filename
