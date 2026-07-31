"""Periodic refresh of the GeoLite2 .mmdb files from MaxMind's download
API. Requires a free MaxMind account (account_id + license_key, see
README) — if unconfigured, GeoIP enrichment is simply skipped, since it's
optional enrichment, not something the login flow depends on.

Runs once at startup (picking up whatever's already on disk first) and
then on a ~monthly timer, matching GeoLite2's own release cadence.
"""
import asyncio
import io
import logging
import tarfile
from pathlib import Path

import httpx

from app import geoip
from app.config import settings

logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://download.maxmind.com/geoip/databases/{edition_id}/download"
UPDATE_INTERVAL_SECONDS = 30 * 24 * 3600
FAILURE_RETRY_SECONDS = 3600

_task: asyncio.Task | None = None


async def _download_edition(client: httpx.AsyncClient, edition_id: str, dest_filename: str) -> bool:
    """Downloads one edition's tar.gz, extracts the .mmdb, and atomically
    replaces the file on disk. Returns True on success, False on any
    failure (network, auth, malformed archive) — logged, never raised, so
    one bad edition doesn't block the other or crash the updater loop."""
    try:
        resp = await client.get(
            DOWNLOAD_URL.format(edition_id=edition_id),
            params={"suffix": "tar.gz"},
            auth=(settings.geoip_account_id, settings.geoip_license_key),
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to download %s from MaxMind", edition_id)
        return False

    try:
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith(".mmdb"))
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError("no .mmdb member found in archive")
            data = extracted.read()
    except Exception:
        logger.exception("Failed to extract .mmdb from %s archive", edition_id)
        return False

    dest = Path(settings.geoip_db_dir) / dest_filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)  # same filesystem, so this is atomic
    logger.info("Updated %s (%d bytes)", dest_filename, len(data))
    return True


async def update_once() -> bool:
    """Returns whether at least one edition is now up to date, so the
    caller can back off quickly on failure instead of waiting a full
    cycle — a transient failure (network blip, a license key that was
    just created and hasn't propagated on MaxMind's side yet) shouldn't
    leave GeoIP disabled for a month."""
    if not settings.geoip_account_id or not settings.geoip_license_key:
        logger.info("GeoIP account/license not configured — skipping database download")
        return True

    async with httpx.AsyncClient(timeout=60) as client:
        city_ok = await _download_edition(client, "GeoLite2-City", "GeoLite2-City.mmdb")
        asn_ok = await _download_edition(client, "GeoLite2-ASN", "GeoLite2-ASN.mmdb")

    if city_ok or asn_ok:
        geoip.reload_readers()
        return True
    return False


async def _periodic_loop() -> None:
    while True:
        success = await update_once()
        await asyncio.sleep(UPDATE_INTERVAL_SECONDS if success else FAILURE_RETRY_SECONDS)


async def start_periodic_updater() -> None:
    global _task
    geoip.reload_readers()  # pick up whatever's already on disk, if anything
    _task = asyncio.create_task(_periodic_loop())


async def stop_periodic_updater() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
