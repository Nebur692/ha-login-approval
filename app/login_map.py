"""The map attached to the sign-in notification: where the address is
(GeoIP), how sure that is (a circle as wide as MaxMind's own accuracy
radius), and whose network it is (the operator's logo and name).

Map tiles come from MAP_TILE_URL (OpenStreetMap by default), with a small
in-memory cache. Everything here is best effort and time-boxed by the caller:
no map is better than a late notification.
"""
import asyncio
import io
import logging
import math
from collections import OrderedDict

import httpx
from PIL import Image, ImageDraw, ImageFont

from app import operator_logo
from app.config import settings
from app.db import get_db
from app.geoip import GeoInfo
from app.safe_fetch import USER_AGENT

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 720, 360
TILE = 256
_RED = (220, 38, 38)
_DEFAULT_ACCURACY_KM = 50
_MAX_TILE_CACHE = 256

_client: httpx.AsyncClient | None = None
_tiles: "OrderedDict[tuple[int, int, int], Image.Image]" = OrderedDict()


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(5.0), headers={"User-Agent": USER_AGENT})
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _metres_per_pixel(latitude: float, zoom: int) -> float:
    return 156543.03392 * math.cos(math.radians(latitude)) / (2 ** zoom)


def zoom_for(latitude: float, accuracy_km: int | None) -> int:
    """The closest zoom at which the accuracy circle still fits: its
    diameter at most two thirds of the map's height."""
    radius_m = (accuracy_km or _DEFAULT_ACCURACY_KM) * 1000
    for zoom in range(15, 1, -1):
        if 2 * radius_m / _metres_per_pixel(latitude, zoom) <= HEIGHT * 2 / 3:
            return zoom
    return 2


def _world_pixel(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    size = TILE * 2 ** zoom
    latitude = max(min(latitude, 85.0511), -85.0511)
    x = (longitude + 180) / 360 * size
    sin = math.sin(math.radians(latitude))
    y = (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * size
    return x, y


async def _tile(zoom: int, x: int, y: int) -> Image.Image | None:
    key = (zoom, x, y)
    if key in _tiles:
        _tiles.move_to_end(key)
        return _tiles[key]
    response = await _http().get(settings.map_tile_url.format(z=zoom, x=x, y=y))
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    _tiles[key] = image
    while len(_tiles) > _MAX_TILE_CACHE:
        _tiles.popitem(last=False)
    return image


async def _base_map(latitude: float, longitude: float, zoom: int) -> Image.Image:
    centre_x, centre_y = _world_pixel(latitude, longitude, zoom)
    left, top = centre_x - WIDTH / 2, centre_y - HEIGHT / 2
    count = 2 ** zoom
    positions = [
        (tx, ty)
        for tx in range(math.floor(left / TILE), math.floor((left + WIDTH) / TILE) + 1)
        for ty in range(math.floor(top / TILE), math.floor((top + HEIGHT) / TILE) + 1)
        if 0 <= ty < count
    ]
    tiles = await asyncio.gather(*(_tile(zoom, tx % count, ty) for tx, ty in positions))
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (170, 211, 223))
    for (tx, ty), tile in zip(positions, tiles):
        canvas.paste(tile, (round(tx * TILE - left), round(ty * TILE - top)))
    return canvas


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def compose(base: Image.Image, latitude: float, zoom: int, accuracy_km: int | None,
            operator_name: str | None, logo_png: bytes | None, attribution: str) -> bytes:
    image = base.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = WIDTH / 2, HEIGHT / 2
    radius = (accuracy_km or _DEFAULT_ACCURACY_KM) * 1000 / _metres_per_pixel(latitude, zoom)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                 fill=(*_RED, 55), outline=(*_RED, 230), width=3)
    draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=(*_RED, 255), outline=(255, 255, 255, 255), width=3)

    small = _font(12)
    text_width = draw.textlength(attribution, font=small)
    draw.rectangle((WIDTH - text_width - 10, HEIGHT - 18, WIDTH, HEIGHT), fill=(255, 255, 255, 210))
    draw.text((WIDTH - text_width - 5, HEIGHT - 16), attribution, font=small, fill=(40, 40, 40, 255))

    logo = None
    if logo_png:
        try:
            logo = Image.open(io.BytesIO(logo_png)).convert("RGBA")
            logo.thumbnail((48, 48), Image.Resampling.LANCZOS)
        except Exception:
            logo = None
    if operator_name or logo:
        name_font = _font(18)
        name = _fit(draw, operator_name or "", name_font, 380)
        pad = 10
        logo_w = (logo.width + pad) if logo else 0
        name_w = draw.textlength(name, font=name_font) if name else 0
        card_w = pad + logo_w + name_w + pad
        card_h = max(logo.height if logo else 0, 22) + 2 * pad
        top = HEIGHT - card_h - 12
        draw.rounded_rectangle((12, top, 12 + card_w, top + card_h), radius=10,
                               fill=(255, 255, 255, 235), outline=(0, 0, 0, 40))
        if logo:
            overlay.alpha_composite(logo, (12 + pad, int(top + (card_h - logo.height) / 2)))
        if name:
            draw.text((12 + pad + logo_w, top + card_h / 2), name, font=name_font,
                      fill=(30, 30, 30, 255), anchor="lm")

    image = Image.alpha_composite(image, overlay).convert("RGB")
    out = io.BytesIO()
    image.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(out, format="PNG", optimize=True)
    return out.getvalue()


async def _render(geo: GeoInfo) -> bytes:
    zoom = zoom_for(geo.latitude, geo.accuracy_km)
    logo_task = None
    if settings.operator_logos and geo.asn is not None:
        logo_task = asyncio.ensure_future(operator_logo.logo_for(get_db(), _http(), geo.asn))
    base = await _base_map(geo.latitude, geo.longitude, zoom)
    logo = None
    if logo_task is not None:
        try:
            logo = await logo_task
        except Exception:
            logger.exception("Operator logo for AS%s failed", geo.asn)
    return compose(base, geo.latitude, zoom, geo.accuracy_km, geo.asn_org, logo,
                   settings.map_tile_attribution)


async def build(geo: GeoInfo) -> bytes | None:
    """The map as PNG bytes, or None when it is switched off, there is no
    location, or it could not be made within MAP_BUDGET_SECONDS."""
    if not settings.notification_map or not settings.idp_issuer_url:
        return None
    if geo.latitude is None or geo.longitude is None:
        return None
    try:
        return await asyncio.wait_for(_render(geo), timeout=settings.map_budget_seconds)
    except asyncio.TimeoutError:
        logger.warning("Map not ready within %.1fs; notification goes without it", settings.map_budget_seconds)
    except Exception:
        logger.exception("Could not draw the sign-in map")
    return None
