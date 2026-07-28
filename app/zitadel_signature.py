"""Verifies the `zitadel-signature` header ZITADEL sends on Action target
calls, so we know a request genuinely came from our ZITADEL instance and
not from anyone who guesses this endpoint's URL.

Format confirmed by capturing a real signed request during this project's
own design phase and reproducing the digest by hand before writing this
code: `zitadel-signature: t=<unix_ts>,v1=<hex hmac-sha256 of "{t}.{raw_body}">`,
keyed with the signing key ZITADEL returns when the Target is created —
the exact same scheme Stripe uses for its webhooks.
"""
import hashlib
import hmac
import time

REPLAY_TOLERANCE_SECONDS = 300


def verify(raw_body: bytes, header_value: str | None, signing_key: str) -> bool:
    if not header_value:
        return False

    parts = dict(p.split("=", 1) for p in header_value.split(",") if "=" in p)
    timestamp, signature = parts.get("t"), parts.get("v1")
    if not timestamp or not signature:
        return False

    try:
        if abs(time.time() - int(timestamp)) > REPLAY_TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False

    expected = hmac.new(
        signing_key.encode(),
        f"{timestamp}.".encode() + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
