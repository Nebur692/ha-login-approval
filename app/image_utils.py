"""Normalizes user-uploaded branding assets (logo, background, favicon).

Uploads can arrive in almost any shape — a phone photo, an old BMP, a
multi-megabyte PNG screenshot, an animated GIF — so every upload is decoded
and re-encoded into a small, predictable file before it ever touches disk,
rather than trusting whatever format/size showed up in the request. Each
asset kind has its own target format and maximum dimensions (never
upscaled, only downscaled); backgrounds additionally get re-compressed
until they're under a size budget, since a full-resolution photo behind a
login page is the case most likely to arrive "muy grande y pesada".
"""
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError


class InvalidImageError(ValueError):
    """Raised when the uploaded bytes can't be decoded as an image."""


@dataclass(frozen=True)
class ImageSpec:
    max_size: tuple[int, int]
    format: str  # "PNG" or "JPEG"
    max_bytes: int | None = None  # JPEG only: re-compress until under this


SPECS: dict[str, ImageSpec] = {
    "favicon": ImageSpec(max_size=(64, 64), format="PNG"),
    "logo": ImageSpec(max_size=(512, 512), format="PNG"),
    "background": ImageSpec(max_size=(1920, 1080), format="JPEG", max_bytes=1_500_000),
}

_MIN_JPEG_QUALITY = 40


def normalize(data: bytes, kind: str) -> tuple[bytes, str]:
    """Decodes `data` (whatever format it arrived in), downscales it to fit
    the given asset kind's bounds, and re-encodes it in that kind's
    standard format. Returns (encoded_bytes, file_extension).

    Raises InvalidImageError if `data` isn't a decodable image.
    """
    spec = SPECS[kind]
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(f"not a supported image format ({exc})") from exc

    image.thumbnail(spec.max_size, Image.Resampling.LANCZOS)

    if spec.format == "JPEG":
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            image = image.convert("RGBA")
            flattened = Image.new("RGB", image.size, (255, 255, 255))
            flattened.paste(image, mask=image.split()[-1])
            image = flattened
        else:
            image = image.convert("RGB")
        ext = "jpg"
    else:
        image = image.convert("RGBA")
        ext = "png"

    return _encode(image, spec), ext


def _encode(image: Image.Image, spec: ImageSpec) -> bytes:
    if spec.format != "JPEG" or spec.max_bytes is None:
        buf = io.BytesIO()
        image.save(buf, format=spec.format, optimize=True)
        return buf.getvalue()

    quality = 90
    encoded = b""
    while True:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality, optimize=True)
        encoded = buf.getvalue()
        if len(encoded) <= spec.max_bytes or quality <= _MIN_JPEG_QUALITY:
            return encoded
        quality -= 10
