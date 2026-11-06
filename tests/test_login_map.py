"""The map in the sign-in notification: drawing it, finding the operator's
logo safely, and its life cycle — public only while the request waits, then
only in the audit log behind the admin sign-in."""
import asyncio
import io
import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from PIL import Image

from app import accounts, audit, db, idp_jwt, login_map, operator_logo, safe_fetch
from app.approval_flow import ApprovalOutcome
from app.config import settings
from app.geoip import GeoInfo
from app.routers import idp as idp_router
from tests.conftest import sign_in

PUBLIC_IP = "93.184.216.34"
EMAIL = "test@example.com"


def _png(width: int, height: int, colour=(0, 120, 200, 255)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (width, height), colour).save(out, format="PNG")
    return out.getvalue()


def _resolve_to(address: str):
    async def fake_getaddrinfo(host):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    return fake_getaddrinfo


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(safe_fetch, "_getaddrinfo", _resolve_to(PUBLIC_IP))


@pytest.fixture
async def map_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "map.db"))
    monkeypatch.setattr(settings, "idp_issuer_url", "https://ha-login.test")
    await db.init_db()
    yield db.get_db()
    await db.close_db()


# --- drawing ---------------------------------------------------------------

def test_zoom_gets_closer_the_more_precise_the_location():
    assert login_map.zoom_for(40.4, 5) > login_map.zoom_for(40.4, 50) > login_map.zoom_for(40.4, 1000)


def test_accuracy_circle_fits_the_map_at_the_chosen_zoom():
    for km in (1, 5, 20, 200, 1000):
        zoom = login_map.zoom_for(40.4, km)
        diameter_px = 2 * km * 1000 / login_map._metres_per_pixel(40.4, zoom)
        assert diameter_px <= login_map.HEIGHT * 2 / 3
        if zoom < 15:  # one step closer would no longer fit
            assert 2 * km * 1000 / login_map._metres_per_pixel(40.4, zoom + 1) > login_map.HEIGHT * 2 / 3


def _colours(png: bytes) -> set:
    return {c for _, c in Image.open(io.BytesIO(png)).convert("RGB").getcolors(1 << 20)}


def test_compose_draws_circle_logo_and_operator_name():
    base = Image.new("RGB", (login_map.WIDTH, login_map.HEIGHT), (200, 200, 200))
    with_logo = login_map.compose(base, 40.4, 6, 200, "Telefonica de Espana", _png(96, 96, (0, 200, 0, 255)), "© OSM")
    image = Image.open(io.BytesIO(with_logo))
    assert image.format == "PNG" and image.size == (login_map.WIDTH, login_map.HEIGHT)
    assert any(r > 200 and g < 60 and b < 60 for r, g, b in _colours(with_logo))   # the red pin
    assert any(g > 180 and r < 40 and b < 40 for r, g, b in _colours(with_logo))   # the logo
    without = login_map.compose(base, 40.4, 6, 200, None, None, "© OSM")
    assert not any(g > 180 and r < 40 and b < 40 for r, g, b in _colours(without))


def test_compose_survives_a_logo_that_is_not_an_image():
    base = Image.new("RGB", (login_map.WIDTH, login_map.HEIGHT), (200, 200, 200))
    assert login_map.compose(base, 0, 3, 100, "Operator", b"not an image", "© OSM")


async def test_build_gives_nothing_without_a_location(map_db):
    assert await login_map.build(GeoInfo(country="ES")) is None


async def test_build_gives_nothing_when_switched_off(map_db, monkeypatch):
    monkeypatch.setattr(settings, "notification_map", False)
    assert await login_map.build(GeoInfo(latitude=40.4, longitude=-3.7, accuracy_km=20)) is None


async def test_build_gives_nothing_without_a_public_url(map_db, monkeypatch):
    monkeypatch.setattr(settings, "idp_issuer_url", "")
    assert await login_map.build(GeoInfo(latitude=40.4, longitude=-3.7, accuracy_km=20)) is None


@respx.mock
async def test_build_draws_the_map_from_tiles(map_db, monkeypatch):
    monkeypatch.setattr(settings, "operator_logos", False)
    login_map._tiles.clear()
    tiles = respx.get(url__regex=r"https://tile\.openstreetmap\.org/\d+/\d+/\d+\.png").mock(
        return_value=httpx.Response(200, content=_png(256, 256, (240, 230, 210, 255))))
    png = await login_map.build(GeoInfo(latitude=40.4, longitude=-3.7, accuracy_km=20, asn_org="Op"))
    assert png and Image.open(io.BytesIO(png)).size == (login_map.WIDTH, login_map.HEIGHT)
    assert tiles.call_count >= 4


@respx.mock
async def test_build_gives_up_within_its_budget(map_db, monkeypatch):
    monkeypatch.setattr(settings, "operator_logos", False)
    monkeypatch.setattr(settings, "map_budget_seconds", 0.2)
    login_map._tiles.clear()

    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, content=_png(256, 256))
    respx.get(url__regex=r"https://tile\.openstreetmap\.org/.*").mock(side_effect=slow)
    started = asyncio.get_running_loop().time()
    assert await login_map.build(GeoInfo(latitude=40.4, longitude=-3.7, accuracy_km=20)) is None
    assert asyncio.get_running_loop().time() - started < 1.5


@respx.mock
async def test_build_without_tiles_gives_nothing_instead_of_failing(map_db, monkeypatch):
    monkeypatch.setattr(settings, "operator_logos", False)
    login_map._tiles.clear()
    respx.get(url__regex=r"https://tile\.openstreetmap\.org/.*").mock(return_value=httpx.Response(503))
    assert await login_map.build(GeoInfo(latitude=40.4, longitude=-3.7, accuracy_km=20)) is None


# --- fetching from addresses strangers chose ---------------------------------

@respx.mock
async def test_safe_fetch_connects_to_the_checked_address(public_dns):
    route = respx.get(f"https://{PUBLIC_IP}/icon.png").mock(return_value=httpx.Response(200, content=b"x"))
    async with httpx.AsyncClient() as client:
        got = await safe_fetch.get(client, "http://operator.test/icon.png", max_bytes=10)
    assert got is not None and got.body == b"x" and got.url == "https://operator.test/icon.png"
    sent = route.calls.last.request
    assert sent.headers["host"] == "operator.test"
    assert sent.extensions["sni_hostname"] == "operator.test"


@pytest.mark.parametrize("address", ["192.168.100.16", "127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00::1"])
@respx.mock
async def test_safe_fetch_refuses_names_that_resolve_inside(monkeypatch, address):
    monkeypatch.setattr(safe_fetch, "_getaddrinfo", _resolve_to(address))
    async with httpx.AsyncClient() as client:
        assert await safe_fetch.get(client, "https://evil.test/", max_bytes=10) is None
    assert respx.calls.call_count == 0


@pytest.mark.parametrize("url", ["https://192.168.1.1/", "ftp://operator.test/", "https://operator.test:8443/",
                                 "https://user:pw@operator.test/", "file:///etc/passwd"])
@respx.mock
async def test_safe_fetch_refuses_unsafe_urls(public_dns, url):
    async with httpx.AsyncClient() as client:
        assert await safe_fetch.get(client, url, max_bytes=10) is None
    assert respx.calls.call_count == 0


@respx.mock
async def test_safe_fetch_checks_every_redirect(monkeypatch):
    answers = {"operator.test": PUBLIC_IP, "inside.test": "192.168.100.16"}

    async def fake_getaddrinfo(host):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers[host], 443))]
    monkeypatch.setattr(safe_fetch, "_getaddrinfo", fake_getaddrinfo)
    respx.get(f"https://{PUBLIC_IP}/").mock(
        return_value=httpx.Response(302, headers={"location": "https://inside.test/admin"}))
    async with httpx.AsyncClient() as client:
        assert await safe_fetch.get(client, "https://operator.test/", max_bytes=10) is None
    assert respx.calls.call_count == 1


@respx.mock
async def test_safe_fetch_cuts_oversized_bodies(public_dns):
    respx.get(f"https://{PUBLIC_IP}/big").mock(return_value=httpx.Response(200, content=b"x" * 1000))
    async with httpx.AsyncClient() as client:
        assert await safe_fetch.get(client, "https://operator.test/big", max_bytes=999) is None
        assert await safe_fetch.get(client, "https://operator.test/big", max_bytes=1000) is not None


# --- operator logo -----------------------------------------------------------

def test_icon_links_prefers_the_biggest_and_skips_svg():
    html = """<head>
      <link rel="icon" href="/favicon-16.png" sizes="16x16">
      <link rel="icon" type="image/svg+xml" href="/logo.svg">
      <link rel="apple-touch-icon" href="/touch.png">
      <LINK REL='shortcut icon' HREF='https://cdn.test/fav.ico?v=1&amp;x=2'>
      <link rel="icon" href="/big.png" sizes="192x192">
      <link rel="stylesheet" href="/site.css">
      <link rel="icon" href="data:image/png;base64,AAAA">
    </head>"""
    assert operator_logo.icon_links(html, "https://op.test/") == [
        "https://op.test/big.png", "https://op.test/touch.png",
        "https://op.test/favicon-16.png", "https://cdn.test/fav.ico?v=1&x=2",
    ]


def test_decode_icon_rejects_what_is_not_a_small_image():
    assert operator_logo.decode_icon(b"<html>") is None
    assert operator_logo.decode_icon(_png(2000, 2000)) is None  # over the pixel cap
    assert operator_logo.decode_icon(_png(64, 64)).size == (64, 64)


def _mock_operator(router, website="https://operator.test", page_icon=(196, 196)):
    peeringdb = router.get(host=PUBLIC_IP, path="/api/net").mock(
        return_value=httpx.Response(200, json={"data": [{"website": website}] if website else []}))
    router.get(f"https://{PUBLIC_IP}/").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"},
        text='<link rel="icon" href="/icons/logo.png" sizes="196x196">'))
    router.get(f"https://{PUBLIC_IP}/icons/logo.png").mock(
        return_value=httpx.Response(200, content=_png(*page_icon, (0, 200, 0, 255))))
    router.get(f"https://{PUBLIC_IP}/apple-touch-icon.png").mock(return_value=httpx.Response(404))
    router.get(f"https://{PUBLIC_IP}/favicon.ico").mock(return_value=httpx.Response(404))
    router.get(host=PUBLIC_IP, path="/s2/favicons").mock(return_value=httpx.Response(200, content=_png(32, 32)))
    return peeringdb


@pytest.mark.respx(assert_all_called=False)
async def test_logo_is_found_once_and_then_served_from_the_database(map_db, public_dns, respx_mock):
    peeringdb = _mock_operator(respx_mock)
    async with httpx.AsyncClient() as client:
        first = await operator_logo.logo_for(map_db, client, 3352)
        second = await operator_logo.logo_for(map_db, client, 3352)
    assert first == second
    logo = Image.open(io.BytesIO(first))
    assert logo.size == (operator_logo.LOGO_SIZE, operator_logo.LOGO_SIZE)
    assert logo.convert("RGB").getpixel((48, 48)) == (0, 200, 0)  # the site's own 196 px icon, not the 32 px one
    assert peeringdb.call_count == 1


@pytest.mark.respx(assert_all_called=False)
async def test_operator_without_website_is_remembered_as_having_no_logo(map_db, public_dns, respx_mock):
    peeringdb = _mock_operator(respx_mock, website=None)
    async with httpx.AsyncClient() as client:
        assert await operator_logo.logo_for(map_db, client, 64512) is None
        assert await operator_logo.logo_for(map_db, client, 64512) is None
    assert peeringdb.call_count == 1


@pytest.mark.respx(assert_all_called=False)
async def test_logo_is_looked_up_again_once_stale(map_db, public_dns, respx_mock):
    peeringdb = _mock_operator(respx_mock)
    await map_db.execute("INSERT INTO operator_logos (asn, png, fetched_at) VALUES (1, NULL, '2000-01-01T00:00:00+00:00')")
    await map_db.commit()
    async with httpx.AsyncClient() as client:
        assert await operator_logo.logo_for(map_db, client, 1) is not None
    assert peeringdb.call_count == 1


async def test_logo_lookup_keeps_going_after_the_caller_stops_waiting(map_db, monkeypatch):
    release = asyncio.Event()

    async def slow_find(client, asn):
        await release.wait()
        return _png(96, 96)
    monkeypatch.setattr(operator_logo, "_find", slow_find)
    async with httpx.AsyncClient() as client:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(operator_logo.logo_for(map_db, client, 7), timeout=0.05)
        release.set()
        await asyncio.sleep(0.05)
    fresh, png = await operator_logo.cached(map_db, 7)
    assert fresh and png


# --- life cycle in a real sign-in ---------------------------------------------

@pytest.fixture
async def idp_ready(map_db, monkeypatch):
    monkeypatch.setattr(settings, "idp_issuer_url", "http://ha-login.test")
    monkeypatch.setattr(settings, "idp_client_id", "test-rp")
    monkeypatch.setattr(settings, "idp_client_secret", "test-rp-secret")
    monkeypatch.setattr(settings, "idp_client_redirect_uri", "https://rp.test/idps/callback")
    await idp_jwt.ensure_signing_key()
    idp_router._pending.clear()
    idp_router._account_attempts.clear()
    yield
    idp_router._pending.clear()
    idp_router._account_attempts.clear()


async def _settled(request_id: str) -> None:
    """Until the background approval has written its audit row (SQLite on a
    slow disk can take far longer than a fixed sleep)."""
    for _ in range(250):
        pending = idp_router._pending.get(request_id, {})
        if pending.get("status") not in (None, "awaiting_email", "waiting") and \
                await audit.list_events(db.get_db(), EMAIL) and \
                any(e["request_id"] == request_id for e in await audit.list_events(db.get_db(), EMAIL)):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the approval never finished")


async def _start_login(client) -> str:
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params={
        "client_id": "test-rp", "redirect_uri": "https://rp.test/idps/callback",
        "response_type": "code", "scope": "openid", "state": "xyz"})
    return idp_router._pending.copy().popitem()[0]


async def test_map_is_public_only_while_waiting_then_only_in_the_audit_log(client, idp_ready, monkeypatch):
    the_map = _png(720, 360, (10, 20, 30, 255))
    seen = {}

    async def phone(targets, request_id, context):
        seen["url"] = context.image_url
        seen["while_waiting"] = await client.get(context.image_url.removeprefix("http://ha-login.test"))
        seen["wrong_token"] = await client.get("/idp/map/not-the-token.png")
        return ApprovalOutcome.APPROVED

    with patch("app.routers.idp.login_map.build", AsyncMock(return_value=the_map)), \
         patch("app.routers.idp.run_approval", phone):
        request_id = await _start_login(client)
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await _settled(request_id)

    assert seen["url"].startswith("http://ha-login.test/idp/map/")
    assert seen["while_waiting"].status_code == 200 and seen["while_waiting"].content == the_map
    assert seen["wrong_token"].status_code == 404
    assert (await client.get(seen["url"].removeprefix("http://ha-login.test"))).status_code == 404

    assert await audit.get_map(db.get_db(), request_id) == the_map
    events = await audit.list_events(db.get_db(), EMAIL)
    assert events[0]["has_map"] == 1

    assert (await client.get(f"/admin/audit/map/{request_id}.png")).status_code in (303, 401)
    await sign_in(client, monkeypatch)
    from_panel = await client.get(f"/admin/audit/map/{request_id}.png")
    assert from_panel.status_code == 200 and from_panel.content == the_map
    page = await client.get("/admin/audit", params={"account_id": EMAIL})
    assert f"/admin/audit/map/{request_id}.png" in page.text


async def test_rejected_and_timed_out_logins_also_close_the_public_map(client, idp_ready):
    for outcome in (ApprovalOutcome.REJECTED, ApprovalOutcome.TIMEOUT):
        with patch("app.routers.idp.login_map.build", AsyncMock(return_value=_png(4, 4))), \
             patch("app.routers.idp.run_approval", AsyncMock(return_value=outcome)) as sent:
            request_id = await _start_login(client)
            await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
            await _settled(request_id)
        url = sent.call_args.args[2].image_url
        assert (await client.get(url.removeprefix("http://ha-login.test"))).status_code == 404
        assert "map_token" not in idp_router._pending[request_id]
        assert await audit.get_map(db.get_db(), request_id) is not None


async def test_without_a_map_the_notification_goes_out_as_before(client, idp_ready):
    with patch("app.routers.idp.login_map.build", AsyncMock(return_value=None)), \
         patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)) as sent:
        request_id = await _start_login(client)
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await _settled(request_id)
    assert sent.call_args.args[2].image_url is None
    assert await audit.get_map(db.get_db(), request_id) is None
    events = await audit.list_events(db.get_db(), EMAIL)
    assert events[0]["has_map"] == 0


async def test_the_map_goes_with_its_last_audit_row(map_db):
    await audit.log_event(map_db, EMAIL, "req-1", "timeout")
    await audit.log_event(map_db, EMAIL, "req-1", "recovery_code_used")
    await audit.store_map(map_db, "req-1", b"png")
    await map_db.execute("DELETE FROM login_events WHERE event_type = 'timeout'")
    assert await audit.get_map(map_db, "req-1") == b"png"
    await map_db.execute("DELETE FROM login_events WHERE request_id = 'req-1'")
    assert await audit.get_map(map_db, "req-1") is None


async def test_notification_carries_the_image_only_when_there_is_one():
    from app import ha_client

    with patch("app.ha_client.call_service", AsyncMock()) as call:
        await ha_client.send_approval_notification("t", "r", "T", "M", "A", "R", image_url="https://x/m.png")
        await ha_client.send_approval_notification("t", "r", "T", "M", "A", "R")
    assert call.call_args_list[0].args[2]["data"]["image"] == "https://x/m.png"
    assert "image" not in call.call_args_list[1].args[2]["data"]


async def test_a_recovery_code_while_the_phone_waits_also_closes_the_public_map(client, idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    never_answered = asyncio.Event()

    async def phone_ignored(targets, request_id, context):
        await never_answered.wait()
        return ApprovalOutcome.TIMEOUT

    with patch("app.routers.idp.login_map.build", AsyncMock(return_value=_png(4, 4))), \
         patch("app.routers.idp.run_approval", phone_ignored):
        request_id = await _start_login(client)
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        for _ in range(250):
            if idp_router._pending[request_id].get("map_token"):
                break
            await asyncio.sleep(0.02)
        url = f"/idp/map/{idp_router._pending[request_id]['map_token']}.png"
        assert (await client.get(url)).status_code == 200

        with patch("app.routers.idp.recovery_codes.verify_code", AsyncMock(return_value=True)), \
             patch("app.routers.idp.ha_client.call_service", AsyncMock()), \
             patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
            resp = await client.post("/idp/recovery", data={"request_id": request_id, "code": "AAAA-AAAA-AAAA"})
        assert resp.status_code == 200
        assert (await client.get(url)).status_code == 404
        assert await audit.get_map(db.get_db(), request_id) is not None
        never_answered.set()
        await asyncio.sleep(0.05)
