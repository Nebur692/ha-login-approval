"""GET from addresses that came from outside — currently an operator's
website, as published in PeeringDB by whoever runs that ASN.

Anyone can register an ASN and point its website at 192.168.1.1, so a plain
GET would let a stranger make this service probe its own network. Here:

- https only (http:// is upgraded), on port 443;
- every address the name resolves to must be a public one, and the
  connection goes to the address that was checked (the name only travels as
  Host and SNI, so a second DNS answer cannot swap it for another);
- redirects are followed by hand, each hop checked the same way;
- the body is cut at `max_bytes`.

Returns None on anything unexpected; callers treat that as "no data".
"""
import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "ha-login-approval (+https://github.com/Nebur692/ha-login-approval)"
_MAX_REDIRECTS = 3


@dataclass
class Fetched:
    url: str
    content_type: str
    body: bytes


class UnsafeAddress(Exception):
    pass


async def _getaddrinfo(host: str) -> list:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)


async def _public_address(host: str) -> str:
    try:
        literal = ipaddress.ip_address(host)
        candidates = [literal]
    except ValueError:
        infos = await _getaddrinfo(host)
        candidates = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not candidates:
        raise UnsafeAddress(f"{host} does not resolve")
    for address in candidates:
        if not address.is_global or address.is_multicast:
            raise UnsafeAddress(f"{host} resolves to {address}, which is not public")
    return str(candidates[0])


def _normalise(url: str) -> tuple[str, str, str] | None:
    """(https URL, host, path+query) or None if it isn't something we fetch."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.port not in (None, 80, 443) or parts.username or parts.password:
        return None
    host = parts.hostname
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return urlunsplit(("https", host, parts.path or "/", parts.query, "")), host, path


async def get(client: httpx.AsyncClient, url: str, *, max_bytes: int) -> Fetched | None:
    for _ in range(_MAX_REDIRECTS + 1):
        normalised = _normalise(url)
        if normalised is None:
            return None
        url, host, path = normalised
        try:
            address = await _public_address(host)
        except (UnsafeAddress, OSError) as exc:
            logger.info("Not fetching %s: %s", url, exc)
            return None
        target = f"[{address}]" if ":" in address else address
        request = client.build_request(
            "GET", f"https://{target}{path}",
            headers={"Host": host, "User-Agent": USER_AGENT},
            extensions={"sni_hostname": host},
        )
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            logger.info("Could not fetch %s: %s", url, exc)
            return None
        try:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            if response.status_code != 200:
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    return None
            return Fetched(url=url, content_type=response.headers.get("content-type", ""), body=bytes(body))
        except httpx.HTTPError as exc:
            logger.info("Could not fetch %s: %s", url, exc)
            return None
        finally:
            await response.aclose()
    return None
