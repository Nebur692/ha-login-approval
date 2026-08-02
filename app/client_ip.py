"""Working out who is actually calling, when a reverse proxy sits in front.

`X-Forwarded-For` is a header, which means it is whatever the sender typed. A
proxy appends to it rather than replacing it, so a request that arrives with a
value already set comes out the other side as `<what the caller wrote>, <the
caller's real address>`. Reading the leftmost entry therefore reads the
caller's own claim about themselves.

That matters here more than in most services, because this address is not just
telemetry: it goes into the approval notification the account holder reads
before tapping yes, into the audit log, and into the per-IP block list.

So the rule is: believe forwarding headers only when the request actually came
from a proxy listed in `TRUSTED_PROXIES`, and then walk the chain from the
right, skipping trusted hops, to find the first address nobody trusted enough
to have written it. With nothing configured, headers are ignored entirely.
"""
import ipaddress
import logging

from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

UNKNOWN = "unknown"


def _networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets = []
    for entry in settings.trusted_proxies:
        try:
            nets.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            logger.warning("Ignoring unparseable TRUSTED_PROXIES entry %r", entry)
    return nets


def is_trusted(address: str) -> bool:
    nets = _networks()
    if not nets:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in net for net in nets)


def resolve(request: Request) -> str:
    """The caller's address, as far as it can be established."""
    peer = request.client.host if request.client else UNKNOWN

    # Nothing configured, or this request did not come from a proxy we listed:
    # the peer address is the only thing here the sender could not choose.
    if not settings.trusted_proxies or not is_trusted(peer):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
        # Right to left: each trailing entry was written by a hop we trust, so
        # the first one that is not a trusted proxy is the real client. Anything
        # further left was supplied by the client and is not evidence.
        for candidate in reversed(entries):
            if not is_trusted(candidate):
                return candidate
        # Every hop was ours — the request never left the proxy chain.
        return entries[0]

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return peer
