"""/health and startup resilience.

Both exist because of the same outage: this service refused to start when
Home Assistant did not answer, uvicorn exited, and the container sat showing
`Up` with a lingering process — 7 days in August 2026, then 15 hours more.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import db, ha_client
from app.config import settings


@pytest.fixture
async def db_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "health.db"))
    await db.init_db()
    yield
    await db.close_db()


async def test_health_is_ok_when_everything_answers(client, db_ready, monkeypatch):
    monkeypatch.setattr(ha_client, "is_ws_healthy", lambda: True)
    monkeypatch.setattr(ha_client, "is_ha_reachable", lambda: True)
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "ha_ws": "connected",
        "ha": "reachable",
        "db": "accessible",
    }


async def test_health_stays_green_while_home_assistant_is_away(client, db_ready, monkeypatch):
    """Home Assistant being down must NOT mark this container unhealthy.

    Painting it red would blame the wrong service, and would hide a real
    crash here behind an outage next door.
    """
    monkeypatch.setattr(ha_client, "is_ws_healthy", lambda: False)
    monkeypatch.setattr(ha_client, "is_ha_reachable", lambda: False)
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["ha"] == "unreachable"
    assert body["db"] == "accessible"


async def test_health_is_503_when_our_own_database_is_gone(client, monkeypatch):
    """The one thing this process owns. This is what the HEALTHCHECK is for."""
    monkeypatch.setattr(ha_client, "is_ws_healthy", lambda: True)
    monkeypatch.setattr(ha_client, "is_ha_reachable", lambda: True)
    monkeypatch.setattr(db, "_db", None)
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["db"] == "unavailable"


async def test_startup_survives_home_assistant_being_unreachable(tmp_path, monkeypatch):
    """The whole point: a container that boots before Home Assistant serves.

    Startup used to raise, uvicorn exited, and nothing came back until
    somebody restarted it by hand days later.
    """
    from main import app

    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "startup.db"))
    monkeypatch.setattr(settings, "branding_asset_dir", str(tmp_path / "branding"))

    started_ws = MagicMock()

    with (
        patch.object(ha_client, "validate_connectivity",
                     AsyncMock(side_effect=httpx.ConnectError("nope"))),
        patch.object(ha_client, "connectivity_watchdog", AsyncMock()),
        patch.object(ha_client, "start_ws_listener", AsyncMock(side_effect=started_ws)),
        patch.object(ha_client, "stop_ws_listener", AsyncMock()),
        patch("app.geoip_updater.start_periodic_updater", AsyncMock()),
        patch("app.geoip_updater.stop_periodic_updater", AsyncMock()),
        patch("app.routers.idp.start_periodic_cleanup", AsyncMock()),
        patch("app.routers.idp.stop_periodic_cleanup", AsyncMock()),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            async with app.router.lifespan_context(app):
                resp = await c.get("/.well-known/openid-configuration")

    assert resp.status_code == 200
    # And the socket listener still got started, so it reconnects on its own.
    assert started_ws.call_count == 1
