import asyncio
import io
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app import geoip_updater
from app.config import settings


def _fake_tar_gz(mmdb_filename: str, content: bytes) -> bytes:
    """Builds a minimal tar.gz matching MaxMind's real download shape:
    a top-level directory containing the .mmdb file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=f"GeoLite2-City_20260101/{mmdb_filename}")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


@pytest.fixture
def updater_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_dir", str(tmp_path))
    monkeypatch.setattr(settings, "geoip_account_id", "test-account")
    monkeypatch.setattr(settings, "geoip_license_key", "test-license-key")
    yield tmp_path


async def test_skips_download_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_dir", str(tmp_path))
    monkeypatch.setattr(settings, "geoip_account_id", "")
    monkeypatch.setattr(settings, "geoip_license_key", "")

    with respx.mock:
        result = await geoip_updater.update_once()
    # No files written, no reload triggered, and treated as success (nothing to retry).
    assert list(tmp_path.iterdir()) == []
    assert result is True


@respx.mock
async def test_downloads_and_extracts_both_editions(updater_ready):
    city_tar = _fake_tar_gz("GeoLite2-City.mmdb", b"fake city data")
    asn_tar = _fake_tar_gz("GeoLite2-ASN.mmdb", b"fake asn data")

    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-City/download").mock(
        return_value=httpx.Response(200, content=city_tar)
    )
    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-ASN/download").mock(
        return_value=httpx.Response(200, content=asn_tar)
    )

    with patch("app.geoip_updater.geoip.reload_readers") as mock_reload:
        result = await geoip_updater.update_once()

    assert (updater_ready / "GeoLite2-City.mmdb").read_bytes() == b"fake city data"
    assert (updater_ready / "GeoLite2-ASN.mmdb").read_bytes() == b"fake asn data"
    mock_reload.assert_called_once()
    assert result is True


@respx.mock
async def test_one_edition_failing_does_not_block_the_other(updater_ready):
    asn_tar = _fake_tar_gz("GeoLite2-ASN.mmdb", b"fake asn data")

    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-City/download").mock(
        return_value=httpx.Response(401)
    )
    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-ASN/download").mock(
        return_value=httpx.Response(200, content=asn_tar)
    )

    with patch("app.geoip_updater.geoip.reload_readers") as mock_reload:
        result = await geoip_updater.update_once()

    assert not (updater_ready / "GeoLite2-City.mmdb").exists()
    assert (updater_ready / "GeoLite2-ASN.mmdb").read_bytes() == b"fake asn data"
    mock_reload.assert_called_once()
    assert result is True


@respx.mock
async def test_both_editions_failing_skips_reload(updater_ready):
    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-City/download").mock(
        return_value=httpx.Response(401)
    )
    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-ASN/download").mock(
        return_value=httpx.Response(401)
    )

    with patch("app.geoip_updater.geoip.reload_readers") as mock_reload:
        result = await geoip_updater.update_once()

    mock_reload.assert_not_called()
    assert result is False


@respx.mock
async def test_periodic_loop_retries_soon_after_a_failure(updater_ready, monkeypatch):
    """A failed attempt (e.g. a freshly-created license key that hasn't
    propagated on MaxMind's side yet) must not lock GeoIP out for a full
    month — it should back off to FAILURE_RETRY_SECONDS instead."""
    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-City/download").mock(
        return_value=httpx.Response(401)
    )
    respx.get("https://download.maxmind.com/geoip/databases/GeoLite2-ASN/download").mock(
        return_value=httpx.Response(401)
    )

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(geoip_updater.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await geoip_updater._periodic_loop()

    assert sleep_calls == [geoip_updater.FAILURE_RETRY_SECONDS]
