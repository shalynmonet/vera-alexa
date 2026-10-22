"""A best-effort check with Vera's own model for a word the built-in word
category lists (vera/word_categories.py) don't recognize -- so a real but
uncommon answer like "platypus" for animals still counts instead of being
silently dropped, while something that clearly doesn't fit ("teapot") still
doesn't.

Entirely optional, same spirit as vera/cloud_storage.py: with no AWS
Bedrock access configured, or on any error, `verify` just returns False --
the caller then reports the word as unmatched rather than guessing at it.
"""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
MODEL_ID = os.environ.get("VERA_BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")

_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=REGION)
    return _client


def _singular(category: str) -> str:
    return category[:-1] if category.endswith("s") else category


def verify(word: str, category: str) -> bool:
    """True if `word` genuinely belongs to `category` (e.g. "platypus" is
    an animal), per a single yes/no judgment call. False for anything that
    doesn't fit, and also whenever we simply can't ask (no AWS configured,
    a network hiccup, etc.) -- the caller treats that the same as "no"."""
    prompt = (
        f'Is "{word}" a kind of {_singular(category)}? Answer with exactly '
        "one word: yes or no."
    )
    try:
        resp = _bedrock().converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 5, "temperature": 0},
        )
        text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
        return text.strip().lower().startswith("y")
    except (ClientError, BotoCoreError, KeyError, IndexError):
        return False
