import hashlib
import hmac
import time

from app.zitadel_signature import verify

SIGNING_KEY = "test-signing-key"


def _sign(body: bytes, ts: int, key: str = SIGNING_KEY) -> str:
    digest = hmac.new(key.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def test_valid_signature_accepted():
    body = b'{"hello":"world"}'
    header = _sign(body, int(time.time()))
    assert verify(body, header, SIGNING_KEY) is True


def test_wrong_key_rejected():
    body = b'{"hello":"world"}'
    header = _sign(body, int(time.time()), key="wrong-key")
    assert verify(body, header, SIGNING_KEY) is False


def test_tampered_body_rejected():
    body = b'{"hello":"world"}'
    header = _sign(body, int(time.time()))
    assert verify(b'{"hello":"WORLD"}', header, SIGNING_KEY) is False


def test_missing_header_rejected():
    assert verify(b"{}", None, SIGNING_KEY) is False


def test_malformed_header_rejected():
    assert verify(b"{}", "not-a-valid-header", SIGNING_KEY) is False


def test_expired_timestamp_rejected():
    body = b'{"hello":"world"}'
    header = _sign(body, int(time.time()) - 10_000)
    assert verify(body, header, SIGNING_KEY) is False


def test_future_timestamp_within_tolerance_accepted():
    body = b'{"hello":"world"}'
    header = _sign(body, int(time.time()) + 60)
    assert verify(body, header, SIGNING_KEY) is True
