import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import admin_sessions, db
from app.config import settings
from app.routers.admin import login as login_router
from tests.conftest import sign_in

GOOD = {"username": "admin", "password": "test-admin-password"}


@pytest.fixture
async def ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "s.db"))
    monkeypatch.setattr(login_router, "_MIN_ANSWER_SECONDS", 0)
    await db.init_db()
    yield
    await db.close_db()


async def _events(kind=None):
    return [e for e in await admin_sessions.list_events() if kind is None or e["event"] == kind]


async def test_right_password_signs_in_and_the_panel_opens(client, ready):
    resp = await client.post("/admin/login", data={**GOOD, "next": "/admin/audit"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/audit"
    assert (await client.get("/admin", follow_redirects=False)).status_code == 200
    assert len(await _events("login_ok")) == 1


@pytest.mark.parametrize("creds", [
    {"username": "admin", "password": "wrong-password-123"},
    {"username": "someone", "password": "test-admin-password"},
    {"username": "", "password": ""},
    {"username": "ádmin", "password": "contraseña-con-eñe"},
])
async def test_wrong_credentials_get_no_session(client, ready, creds):
    resp = await client.post("/admin/login", data=creds)
    assert resp.status_code == 401
    assert "Wrong username or password." in resp.text
    assert "set-cookie" not in resp.headers
    assert (await client.get("/admin", follow_redirects=False)).status_code == 303
    assert len(await _events("login_failed")) == 1


async def test_cookie_is_httponly_strict_and_only_a_hash_is_stored(client, ready):
    resp = await client.post("/admin/login", data=GOOD)
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("hla_admin=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    token = cookie.split(";")[0].split("=", 1)[1]
    cursor = await db.get_db().execute("SELECT token_hash FROM admin_sessions")
    stored = [row[0] for row in await cursor.fetchall()]
    assert stored == [admin_sessions.hash_of(token)] and token not in stored


async def test_over_https_the_cookie_is_secure_and_host_only(client, ready, monkeypatch):
    monkeypatch.setattr(settings, "idp_issuer_url", "https://ha-login.example.com")
    cookie = (await client.post("/admin/login", data=GOOD)).headers["set-cookie"]
    assert cookie.startswith("__Host-hla_admin=")
    assert "Secure" in cookie and "Domain" not in cookie


async def test_sign_out_ends_the_session_for_good(client, ready, monkeypatch):
    csrf = await sign_in(client, monkeypatch)
    token = client.cookies.get("hla_admin")
    resp = await client.post("/admin/logout", data={"csrf_token": csrf}, follow_redirects=False)
    assert resp.status_code == 303
    # the old cookie, replayed, opens nothing
    client.cookies.set("hla_admin", token)
    assert (await client.get("/admin", follow_redirects=False)).status_code == 303
    assert len(await _events("logout")) == 1


@pytest.mark.parametrize("column,age", [("last_seen_at", timedelta(minutes=31)), ("created_at", timedelta(hours=9))])
async def test_idle_or_old_sessions_expire(client, ready, monkeypatch, column, age):
    await sign_in(client, monkeypatch)
    past = (datetime.now(timezone.utc) - age).isoformat()
    await db.get_db().execute(f"UPDATE admin_sessions SET {column} = ?", (past,))
    await db.get_db().commit()
    assert (await client.get("/admin", follow_redirects=False)).status_code == 303


async def test_using_the_panel_keeps_the_session_alive(client, ready, monkeypatch):
    await sign_in(client, monkeypatch)
    past = (datetime.now(timezone.utc) - timedelta(minutes=29)).isoformat()
    await db.get_db().execute("UPDATE admin_sessions SET last_seen_at = ?", (past,))
    await db.get_db().commit()
    assert (await client.get("/admin", follow_redirects=False)).status_code == 200
    cursor = await db.get_db().execute("SELECT last_seen_at FROM admin_sessions")
    assert (await cursor.fetchone())[0] > past


async def test_five_failures_lock_the_address_even_for_the_right_password(client, ready):
    for _ in range(admin_sessions.FAILURES_PER_ADDRESS):
        assert (await client.post("/admin/login", data={**GOOD, "password": "nope-nope-nope"})).status_code == 401
    resp = await client.post("/admin/login", data=GOOD)
    assert resp.status_code == 429
    assert "set-cookie" not in resp.headers
    assert len(await _events("login_refused")) == 1


async def test_four_failures_do_not_lock(client, ready):
    for _ in range(admin_sessions.FAILURES_PER_ADDRESS - 1):
        await client.post("/admin/login", data={**GOOD, "password": "nope-nope-nope"})
    assert (await client.post("/admin/login", data=GOOD)).status_code == 303


async def test_old_failures_no_longer_count(client, ready):
    for _ in range(admin_sessions.FAILURES_PER_ADDRESS):
        await client.post("/admin/login", data={**GOOD, "password": "nope-nope-nope"})
    past = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    await db.get_db().execute("UPDATE admin_events SET at = ?", (past,))
    await db.get_db().commit()
    assert (await client.post("/admin/login", data=GOOD)).status_code == 303


async def test_failures_from_many_addresses_do_not_lock_anyone_else(client, ready):
    """Only per address: an overall limit would let anyone with enough
    addresses keep the owner out of the panel."""
    for i in range(200):
        await admin_sessions.record(admin_sessions.LOGIN_FAILED, username="admin", ip=f"198.51.100.{i}")
    assert (await client.post("/admin/login", data=GOOD)).status_code == 303


@pytest.mark.parametrize("weak", ["short1234", "changeme", "Password", "", "admin"])
async def test_a_weak_password_turns_the_panel_off(client, ready, monkeypatch, weak):
    monkeypatch.setattr(settings, "admin_password", weak)
    page = await client.get("/admin/login")
    assert "The admin panel is turned off" in page.text
    resp = await client.post("/admin/login", data={"username": "admin", "password": weak})
    assert resp.status_code == 403
    assert "set-cookie" not in resp.headers


@pytest.mark.parametrize("password", ["twelve-chars", "a much longer passphrase ñ"])
async def test_a_good_password_is_accepted(client, ready, monkeypatch, password):
    monkeypatch.setattr(settings, "admin_password", password)
    assert admin_sessions.password_problem() is None
    assert (await client.post("/admin/login", data={"username": "admin", "password": password})).status_code == 303


@pytest.mark.parametrize("target", ["//evil.example/x", "https://evil.example", "/somewhere-else", ""])
async def test_next_never_leaves_the_panel(client, ready, target):
    resp = await client.post("/admin/login", data={**GOOD, "next": target})
    assert resp.headers["location"] == "/admin"


async def test_every_sign_in_answer_takes_at_least_a_second(client, ready, monkeypatch):
    monkeypatch.setattr(login_router, "_MIN_ANSWER_SECONDS", 1.0)
    for data in (GOOD, {**GOOD, "password": "nope-nope-nope"}):
        started = time.monotonic()
        await client.post("/admin/login", data=data)
        assert time.monotonic() - started >= 1.0


async def test_changes_are_recorded_with_who_and_what(client, ready, monkeypatch):
    from unittest.mock import AsyncMock, patch

    csrf = await sign_in(client, monkeypatch)
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        await client.post("/admin/accounts/save", data={"email": "Bob@Example.com", "targets": ["mobile_app_x"], "csrf_token": csrf})
    await client.post("/admin/recovery/generate", data={"email": "bob@example.com", "csrf_token": csrf})
    await client.post("/admin/signing-key/rotate", data={"csrf_token": csrf})
    kinds = [e["event"] for e in await _events()]
    assert kinds[:3] == ["signing_key_rotated", "recovery_codes_generated", "account_saved"]
    saved = (await _events("account_saved"))[0]
    assert saved["username"] == "admin" and saved["detail"] == "bob@example.com: mobile_app_x"
    page = await client.get("/admin/activity")
    assert "account saved" in page.text and "bob@example.com: mobile_app_x" in page.text


async def test_ending_another_session_from_the_activity_page(client, ready, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await sign_in(other, monkeypatch)
        csrf = await sign_in(client, monkeypatch)
        sessions = await admin_sessions.list_sessions()
        assert len(sessions) == 2
        mine = admin_sessions.hash_of(client.cookies.get("hla_admin"))
        theirs = next(s["token_hash"] for s in sessions if s["token_hash"] != mine)

        resp = await client.post("/admin/activity/end-session", data={"token_hash": theirs, "csrf_token": csrf}, follow_redirects=False)
        assert resp.headers["location"] == "/admin/activity"
        assert (await other.get("/admin", follow_redirects=False)).status_code == 303
        assert (await client.get("/admin", follow_redirects=False)).status_code == 200

        resp = await client.post("/admin/activity/end-session", data={"token_hash": mine, "csrf_token": csrf}, follow_redirects=False)
        assert resp.headers["location"] == "/admin/login"
        assert (await client.get("/admin", follow_redirects=False)).status_code == 303


async def test_sign_in_errors_end_with_their_burburito_code(client, ready, monkeypatch):
    wrong = await client.post("/admin/login", data={**GOOD, "password": "nope-nope-nope"})
    assert "Burburito code: <code>003-001-001-041</code>" in wrong.text
    assert "You DO need to do something." in wrong.text
    for _ in range(admin_sessions.FAILURES_PER_ADDRESS):
        await client.post("/admin/login", data={**GOOD, "password": "nope-nope-nope"})
    locked = await client.post("/admin/login", data=GOOD)
    assert "003-001-001-141" in locked.text and "You do NOT need to do anything." in locked.text
    monkeypatch.setattr(settings, "admin_password", "short")
    assert "003-001-001-101" in (await client.get("/admin/login")).text


async def test_refused_changes_are_a_page_with_their_code_not_json(client, ready, monkeypatch):
    stranger = await client.post("/admin/accounts/save", data={"email": "x@example.com"})
    assert stranger.status_code == 403 and stranger.headers["content-type"].startswith("text/html")
    assert "003-001-007-044" in stranger.text and 'href="/admin/login"' in stranger.text
    await sign_in(client, monkeypatch)
    forged = await client.post("/admin/accounts/save", data={"email": "x@example.com", "csrf_token": "old"})
    assert forged.status_code == 403
    assert "003-001-007-046" in forged.text and "Nothing was changed" in forged.text
