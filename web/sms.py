"""Optional SMS for family cheer nudges, via AWS End User Messaging SMS
(the pinpoint-sms-voice-v2 API).

Off by default (VERA_SMS_ENABLED), and not usable at all until a toll-free
number is registered with AWS and set as VERA_SMS_ORIGINATION_NUMBER --
that's an AWS console process with its own review/approval time, well
outside what a hackathon demo can complete, so this exists ready to flip
on rather than actually wired into the live demo. The one SMS the app
sends today -- the initial family invite -- never goes through this
module at all: it's a plain `sms:` link that opens the person's own phone
Messages app, so it works with zero AWS setup and from day one.

Failures here are caught and surfaced as a clear error, never crash the
caller; email and the copy-link button always work regardless.
"""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
ENABLED = os.environ.get("VERA_SMS_ENABLED", "false").strip().lower() == "true"
ORIGINATION_NUMBER = os.environ.get("VERA_SMS_ORIGINATION_NUMBER")

_client = None


def enabled() -> bool:
    return ENABLED


def _sms():
    global _client
    if _client is None:
        _client = boto3.client("pinpoint-sms-voice-v2", region_name=REGION)
    return _client


class SMSError(RuntimeError):
    pass


def send_nudge_sms(to_phone: str, body: str) -> None:
    if not ENABLED:
        raise SMSError("SMS is disabled (set VERA_SMS_ENABLED=true once a toll-free number is registered).")
    if not ORIGINATION_NUMBER:
        raise SMSError("VERA_SMS_ORIGINATION_NUMBER is not configured.")
    text = body.rstrip()
    if "stop" not in text.lower():
        text += "\n\nReply STOP to opt out."
    try:
        _sms().send_text_message(
            DestinationPhoneNumber=to_phone,
            OriginationIdentity=ORIGINATION_NUMBER,
            MessageBody=text,
            MessageType="PROMOTIONAL",
        )
    except (ClientError, BotoCoreError) as e:
        raise SMSError(str(e)) from e
