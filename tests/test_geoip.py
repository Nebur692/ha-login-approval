import shutil
from pathlib import Path

import pytest

from app import geoip
from app.config import settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def geoip_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_dir", str(tmp_path))
    shutil.copy(FIXTURES / "GeoLite2-City-Test.mmdb", tmp_path / "GeoLite2-City.mmdb")
    shutil.copy(FIXTURES / "GeoLite2-ASN-Test.mmdb", tmp_path / "GeoLite2-ASN.mmdb")
    geoip.reload_readers()
    yield
    geoip.close_readers()


def test_city_lookup_known_ip(geoip_ready):
    info = geoip.lookup("81.2.69.142")
    assert info.city == "London"
    assert info.country == "GB"


def test_asn_lookup_known_ip(geoip_ready):
    info = geoip.lookup("1.128.0.0")
    assert info.asn_org == "Telstra Pty Ltd"


def test_partial_result_when_ip_only_in_city_db(geoip_ready):
    """175.16.199.1 is in the City test fixture but not the ASN one —
    the ASN field should just stay None, not raise."""
    info = geoip.lookup("175.16.199.1")
    assert info.city == "Changchun"
    assert info.country == "CN"
    assert info.asn_org is None


def test_unknown_ip_returns_all_none(geoip_ready):
    info = geoip.lookup("203.0.113.1")
    assert info.city is None
    assert info.country is None
    assert info.asn_org is None


def test_missing_database_files_degrade_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_dir", str(tmp_path))  # empty dir, no .mmdb files
    geoip.reload_readers()
    info = geoip.lookup("81.2.69.142")
    assert info == geoip.GeoInfo()
    geoip.close_readers()


def test_corrupt_database_file_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_dir", str(tmp_path))
    (tmp_path / "GeoLite2-City.mmdb").write_bytes(b"not a real mmdb file")
    geoip.reload_readers()
    info = geoip.lookup("81.2.69.142")
    assert info.city is None
    geoip.close_readers()
