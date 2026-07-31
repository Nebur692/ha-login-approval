import io

import pytest
from PIL import Image

from app import image_utils


def _encode(image: Image.Image, format: str) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=format)
    return buf.getvalue()


def test_rejects_bytes_that_arent_an_image():
    with pytest.raises(image_utils.InvalidImageError):
        image_utils.normalize(b"this is not an image", "logo")


def test_converts_a_non_standard_format_to_the_target_format():
    # BMP is a "non-standard" format for the web — logo/favicon must come
    # out as PNG regardless of what went in.
    bmp = _encode(Image.new("RGB", (100, 100), (10, 20, 30)), "BMP")

    encoded, ext = image_utils.normalize(bmp, "logo")

    assert ext == "png"
    assert Image.open(io.BytesIO(encoded)).format == "PNG"


def test_favicon_is_downscaled_to_its_max_size():
    huge = _encode(Image.new("RGB", (2000, 2000), (200, 0, 0)), "PNG")

    encoded, ext = image_utils.normalize(huge, "favicon")

    result = Image.open(io.BytesIO(encoded))
    assert ext == "png"
    assert result.size == (64, 64)


def test_logo_is_downscaled_preserving_aspect_ratio():
    wide = _encode(Image.new("RGB", (4000, 1000), (0, 200, 0)), "PNG")

    encoded, _ = image_utils.normalize(wide, "logo")

    result = Image.open(io.BytesIO(encoded))
    assert result.width == 512
    assert result.height == 128  # 4000:1000 ratio preserved at the new width


def test_small_image_is_not_upscaled():
    tiny = _encode(Image.new("RGB", (16, 16), (0, 0, 200)), "PNG")

    encoded, _ = image_utils.normalize(tiny, "favicon")

    assert Image.open(io.BytesIO(encoded)).size == (16, 16)


def test_background_flattens_transparency_onto_white_before_converting_to_jpeg():
    transparent = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    data = _encode(transparent, "PNG")

    encoded, ext = image_utils.normalize(data, "background")

    result = Image.open(io.BytesIO(encoded))
    assert ext == "jpg"
    assert result.mode == "RGB"
    assert result.getpixel((50, 50)) == (255, 255, 255)


def test_background_is_recompressed_under_the_size_budget(monkeypatch):
    # A smooth gradient (like a real photo, unlike pure noise) compresses
    # well, so a budget that's tight relative to quality-90 output but
    # still realistically reachable should make the loop drop the quality.
    tiny_spec = image_utils.ImageSpec(max_size=(256, 256), format="JPEG", max_bytes=3000)
    monkeypatch.setitem(image_utils.SPECS, "background", tiny_spec)

    gradient = Image.new("RGB", (256, 256))
    for x in range(256):
        for y in range(256):
            gradient.putpixel((x, y), (x, y, (x + y) % 256))
    data = _encode(gradient, "PNG")

    encoded, ext = image_utils.normalize(data, "background")

    assert ext == "jpg"
    assert len(encoded) <= tiny_spec.max_bytes


def test_background_stops_at_minimum_quality_even_if_still_over_budget():
    # An impossible-to-hit budget must still terminate instead of looping
    # forever, bottoming out at _MIN_JPEG_QUALITY.
    tiny_spec = image_utils.ImageSpec(max_size=(256, 256), format="JPEG", max_bytes=1)
    noise = Image.effect_noise((256, 256), 80).convert("RGB")

    encoded = image_utils._encode(Image.open(io.BytesIO(_encode(noise, "PNG"))).convert("RGB"), tiny_spec)

    assert len(encoded) > 0
