"""Optional Amazon SES email for family cheer nudges.

SES sandbox mode (the default for a new AWS account) requires both the
sender and every recipient to be verified identities, so this will fail
until that's set up -- an AWS console/CLI action the user does themselves,
same as granting the Bedrock/Polly IAM permissions. Failures here are
caught and surfaced as a clear error, never crash the dashboard; copying
the record link always works regardless of email.
"""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
FROM_EMAIL = os.environ.get("VERA_SES_FROM_EMAIL")

_client = None


def _ses():
    global _client
    if _client is None:
        _client = boto3.client("ses", region_name=REGION)
    return _client


class EmailError(RuntimeError):
    pass


def send_nudge_email(to_email: str, subject: str, body_text: str) -> None:
    if not FROM_EMAIL:
        raise EmailError("VERA_SES_FROM_EMAIL is not configured.")
    try:
        _ses().send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body_text}},
            },
        )
    except (ClientError, BotoCoreError) as e:
        raise EmailError(str(e)) from e
