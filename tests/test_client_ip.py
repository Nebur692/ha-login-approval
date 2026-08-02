"""Establishing the caller's address behind a reverse proxy.

This is not bookkeeping: the address chosen here is printed in the approval
notification the account holder reads before tapping yes, written to the audit
log, and used as the key for the per-IP block list. If the caller can choose
it, they can choose what all three say about them.
"""
import pytest

from app import client_ip
from app.config import settings


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Only the two things resolve() reads."""

    def __init__(self, peer, headers=None):
        self.client = _FakeClient(peer) if peer else None
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _restore_trusted_proxies():
    original = list(settings.trusted_proxies)
    yield
    settings.trusted_proxies = original


# ---------------------------------------------------------------------------
# Nothing configured: headers are not evidence
# ---------------------------------------------------------------------------

def test_forwarding_headers_are_ignored_when_no_proxy_is_configured():
    settings.trusted_proxies = []
    request = _FakeRequest("203.0.113.9", {"x-forwarded-for": "10.0.0.1"})

    assert client_ip.resolve(request) == "203.0.113.9"


def test_x_real_ip_is_ignored_too_when_no_proxy_is_configured():
    settings.trusted_proxies = []
    request = _FakeRequest("203.0.113.9", {"x-real-ip": "10.0.0.1"})

    assert client_ip.resolve(request) == "203.0.113.9"


# ---------------------------------------------------------------------------
# Configured: only a listed proxy is believed
# ---------------------------------------------------------------------------

def test_a_request_straight_from_the_internet_cannot_claim_an_address():
    """The container is reachable without going through the proxy, so this is
    a real path, not a hypothetical one."""
    settings.trusted_proxies = ["172.18.0.5"]
    request = _FakeRequest("203.0.113.9", {"x-forwarded-for": "192.168.1.50"})

    assert client_ip.resolve(request) == "203.0.113.9"


def test_the_proxy_is_believed_about_who_called_it():
    settings.trusted_proxies = ["172.18.0.5"]
    request = _FakeRequest("172.18.0.5", {"x-forwarded-for": "203.0.113.9"})

    assert client_ip.resolve(request) == "203.0.113.9"


def test_a_forged_prefix_is_discarded():
    """A proxy appends rather than replaces, so anything the caller wrote
    arrives to the left of their real address. Reading left to right reads
    their claim; reading right to left reads the record."""
    settings.trusted_proxies = ["172.18.0.5"]
    request = _FakeRequest(
        "172.18.0.5", {"x-forwarded-for": "192.168.1.50, 8.8.8.8, 203.0.113.9"}
    )

    assert client_ip.resolve(request) == "203.0.113.9"


def test_chained_proxies_are_skipped_to_reach_the_client():
    settings.trusted_proxies = ["172.18.0.0/16", "10.1.0.0/16"]
    request = _FakeRequest(
        "172.18.0.5", {"x-forwarded-for": "203.0.113.9, 10.1.2.3, 172.18.0.9"}
    )

    assert client_ip.resolve(request) == "203.0.113.9"


def test_cidr_ranges_are_honoured():
    settings.trusted_proxies = ["172.18.0.0/16"]
    request = _FakeRequest("172.18.4.7", {"x-forwarded-for": "203.0.113.9"})

    assert client_ip.resolve(request) == "203.0.113.9"


def test_a_request_that_never_left_the_proxy_chain_falls_back():
    settings.trusted_proxies = ["172.18.0.0/16"]
    request = _FakeRequest("172.18.0.5", {"x-forwarded-for": "172.18.0.9"})

    assert client_ip.resolve(request) == "172.18.0.9"


def test_x_real_ip_is_used_when_the_proxy_sends_only_that():
    settings.trusted_proxies = ["172.18.0.5"]
    request = _FakeRequest("172.18.0.5", {"x-real-ip": "203.0.113.9"})

    assert client_ip.resolve(request) == "203.0.113.9"


# ---------------------------------------------------------------------------
# Malformed input must not become a trusted answer
# ---------------------------------------------------------------------------

def test_garbage_entries_are_never_treated_as_proxies():
    settings.trusted_proxies = ["172.18.0.5"]
    request = _FakeRequest("172.18.0.5", {"x-forwarded-for": "not-an-address"})

    # Unparseable, so untrusted, so it is taken as the client's address —
    # meaningless, but never mistaken for one of ours.
    assert client_ip.resolve(request) == "not-an-address"


def test_an_unparseable_configuration_entry_is_skipped_not_trusted():
    settings.trusted_proxies = ["definitely not a cidr"]
    request = _FakeRequest("172.18.0.5", {"x-forwarded-for": "192.168.1.50"})

    assert client_ip.resolve(request) == "172.18.0.5"


def test_a_request_with_no_peer_at_all():
    settings.trusted_proxies = []

    assert client_ip.resolve(_FakeRequest(None)) == client_ip.UNKNOWN


def test_empty_entries_in_the_header_are_ignored():
    settings.trusted_proxies = ["172.18.0.5"]
    request = _FakeRequest("172.18.0.5", {"x-forwarded-for": " , 203.0.113.9 , "})

    assert client_ip.resolve(request) == "203.0.113.9"
