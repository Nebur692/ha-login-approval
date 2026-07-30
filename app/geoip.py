"""GeoIP enrichment via self-hosted MaxMind GeoLite2 databases (City + ASN)
— chosen over per-login third-party APIs (ipapi.co, ipinfo.io, etc.) for
privacy (the login IP never leaves this server) and availability (no
external network call on the login's critical path). The databases are
just files on disk, refreshed periodically by geoip_updater.py.

City and ASN are independent databases/readers — a lookup degrades
gracefully field-by-field (missing file, corrupt file, or the IP simply
not being in that particular database) rather than failing the whole
lookup or crashing the login flow, since this is enrichment, not something
the flow depends on to function.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

import geoip2.database
import geoip2.errors

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GeoInfo:
    city: str | None = None
    country: str | None = None
    asn_org: str | None = None


_city_reader: geoip2.database.Reader | None = None
_asn_reader: geoip2.database.Reader | None = None


def city_db_path() -> Path:
    return Path(settings.geoip_db_dir) / "GeoLite2-City.mmdb"


def asn_db_path() -> Path:
    return Path(settings.geoip_db_dir) / "GeoLite2-ASN.mmdb"


def reload_readers() -> None:
    """(Re)opens the reader(s) from disk. Called at startup and again after
    geoip_updater.py downloads a fresh copy. Never raises — a missing or
    corrupt file just means that reader stays None."""
    global _city_reader, _asn_reader

    try:
        _city_reader = geoip2.database.Reader(str(city_db_path()))
    except Exception:
        logger.warning("GeoLite2-City.mmdb not available — city/country enrichment disabled")
        _city_reader = None

    try:
        _asn_reader = geoip2.database.Reader(str(asn_db_path()))
    except Exception:
        logger.warning("GeoLite2-ASN.mmdb not available — ISP/org enrichment disabled")
        _asn_reader = None


def close_readers() -> None:
    global _city_reader, _asn_reader
    if _city_reader:
        _city_reader.close()
        _city_reader = None
    if _asn_reader:
        _asn_reader.close()
        _asn_reader = None


def lookup(ip: str) -> GeoInfo:
    info = GeoInfo()

    if _city_reader is not None:
        try:
            city_resp = _city_reader.city(ip)
            info.city = city_resp.city.name
            info.country = city_resp.country.iso_code
        except (geoip2.errors.AddressNotFoundError, ValueError):
            pass

    if _asn_reader is not None:
        try:
            asn_resp = _asn_reader.asn(ip)
            info.asn_org = asn_resp.autonomous_system_organization
        except (geoip2.errors.AddressNotFoundError, ValueError):
            pass

    return info
