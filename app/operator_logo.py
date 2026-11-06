"""The network operator's logo for the map: ASN -> website (PeeringDB) ->
the biggest icon that website publishes.

Looked up once per ASN and kept in the database — 30 days when found, 7 when
not, so an operator with no logo is not asked again on every sign-in. Every
download goes through safe_fetch, since both the website and the icon links
on it come from strangers.
"""
import asyncio
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urljoin, urlsplit

import httpx
from PIL import Image

from app import safe_fetch

logger = logging.getLogger(__name__)

PEERINGDB_URL = "https://www.peeringdb.com/api/net?asn={asn}&fields=website"
FALLBACK_ICON_URL = "https://www.google.com/s2/favicons?domain={host}&sz=128"
LOGO_SIZE = 96
_FOUND_TTL = timedelta(days=30)
_MISSING_TTL = timedelta(days=7)
_MAX_PAGE_BYTES = 512 * 1024
_MAX_ICON_BYTES = 512 * 1024
_MAX_CANDIDATES = 6
_GOOD_ENOUGH = 128
_MAX_ICON_PIXELS = 1024 * 1024
_ICON_FORMATS = {"PNG", "ICO", "JPEG", "GIF", "WEBP", "BMP"}

_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([a-zA-Z-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")

_in_flight: dict[int, asyncio.Task] = {}


async def cached(db, asn: int) -> tuple[bool, bytes | None]:
    """(fresh, png): fresh=False means it must be (re)looked up."""
    cursor = await db.execute("SELECT png, fetched_at FROM operator_logos WHERE asn = ?", (asn,))
    row = await cursor.fetchone()
    if row is None:
        return False, None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
    return age < (_FOUND_TTL if row["png"] is not None else _MISSING_TTL), row["png"]


async def _store(db, asn: int, png: bytes | None) -> None:
    await db.execute(
        "INSERT INTO operator_logos (asn, png, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(asn) DO UPDATE SET png = excluded.png, fetched_at = excluded.fetched_at",
        (asn, png, datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()


def icon_links(html: str, base_url: str) -> list[str]:
    """Icon URLs a page declares, biggest declared size first, SVG left out
    (it cannot be drawn here)."""
    found = []
    for tag in _LINK_TAG.findall(html):
        attrs = {k.lower(): unescape(v.strip("'\"")) for k, v in _ATTR.findall(tag)}
        if "icon" not in attrs.get("rel", "").lower() or not attrs.get("href"):
            continue
        href = attrs["href"]
        if href.startswith("data:") or ".svg" in href.lower().split("?")[0] or "svg" in attrs.get("type", ""):
            continue
        sizes = [int(n) for n in re.findall(r"(\d+)x\d+", attrs.get("sizes", ""))]
        size = max(sizes) if sizes else (180 if "apple-touch-icon" in attrs["rel"].lower() else 0)
        found.append((size, urljoin(base_url, href)))
    found.sort(key=lambda item: -item[0])
    return [url for _, url in found]


def decode_icon(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in _ICON_FORMATS:
                return None
            width, height = probe.size
            if width * height > _MAX_ICON_PIXELS:
                return None
            probe.load()
            return probe.convert("RGBA")
    except Exception:
        return None


def normalise_logo(image: Image.Image) -> bytes:
    image = image.copy()
    image.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    canvas.paste(image, ((LOGO_SIZE - image.width) // 2, (LOGO_SIZE - image.height) // 2))
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def _website(client: httpx.AsyncClient, asn: int) -> str | None:
    fetched = await safe_fetch.get(client, PEERINGDB_URL.format(asn=asn), max_bytes=64 * 1024)
    if fetched is None:
        return None
    try:
        data = json.loads(fetched.body).get("data") or []
    except ValueError:
        return None
    website = (data[0].get("website") or "").strip() if data else ""
    return website or None


async def _find(client: httpx.AsyncClient, asn: int) -> bytes | None:
    website = await _website(client, asn)
    if website is None:
        return None
    host = urlsplit(website if "://" in website else f"https://{website}").hostname
    if not host:
        return None
    home = f"https://{host}/"

    candidates = []
    page = await safe_fetch.get(client, home, max_bytes=_MAX_PAGE_BYTES)
    if page is not None and "html" in page.content_type:
        candidates += icon_links(page.body.decode("utf-8", "replace"), page.url)
    candidates += [urljoin(home, "/apple-touch-icon.png"), urljoin(home, "/favicon.ico"),
                   FALLBACK_ICON_URL.format(host=quote(host))]

    best = None
    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        if len(seen) > _MAX_CANDIDATES:
            break
        fetched = await safe_fetch.get(client, url, max_bytes=_MAX_ICON_BYTES)
        icon = decode_icon(fetched.body) if fetched else None
        if icon is None or min(icon.size) < 16:
            continue
        if best is None or min(icon.size) > min(best.size):
            best = icon
        if min(best.size) >= _GOOD_ENOUGH:
            break
    return normalise_logo(best) if best is not None else None


async def _lookup_and_store(db, client: httpx.AsyncClient, asn: int) -> bytes | None:
    try:
        png = await _find(client, asn)
    except Exception:
        logger.exception("Operator logo lookup for AS%s failed", asn)
        return None  # not stored: a crash is not "this operator has no logo"
    await _store(db, asn, png)
    return png


async def logo_for(db, client: httpx.AsyncClient, asn: int | None) -> bytes | None:
    """The cached logo, or a fresh lookup. The lookup runs as its own task:
    if the caller stops waiting (the notification will not wait for it), it
    still finishes and fills the cache for the next sign-in."""
    if asn is None:
        return None
    fresh, png = await cached(db, asn)
    if fresh:
        return png
    task = _in_flight.get(asn)
    if task is None:
        task = asyncio.create_task(_lookup_and_store(db, client, asn))
        _in_flight[asn] = task
        task.add_done_callback(lambda _t, key=asn: _in_flight.pop(key, None))
    found = await asyncio.shield(task)
    return found if found is not None else png
