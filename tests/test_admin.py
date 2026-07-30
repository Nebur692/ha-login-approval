import base64
from unittest.mock import AsyncMock, patch

import pytest

from app import accounts, db
from app.config import settings

AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-password").decode()}

ADMIN_ROUTES = [
    ("GET", "/admin"),
    ("GET", "/admin/accounts"),
    ("GET", "/admin/devices"),
    ("GET", "/admin/audit"),
    ("GET", "/admin/recovery"),
    ("GET", "/admin/blocked-ips"),
    ("GET", "/admin/branding"),
]

FAKE_ZITADEL_USERS = [
    {"id": "u1", "username": "alice@example.com", "display_name": "Alice", "email": "alice@example.com", "is_machine": False},
]


@pytest.fixture
async def admin_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "admin.db"))
    monkeypatch.setattr(settings, "branding_asset_dir", str(tmp_path / "branding"))
    await db.init_db()
    yield
    await db.close_db()


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
async def test_every_admin_route_requires_basic_auth(client, admin_ready, method, path):
    with patch("app.routers.admin.devices.ha_client.get_notify_targets", AsyncMock(return_value=[])), \
         patch("app.routers.admin.devices.zitadel_client.list_users", AsyncMock(return_value=[])), \
         patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=[])):
        resp = await client.request(method, path)
    assert resp.status_code == 401


async def test_home_page_shows_counts(client, admin_ready):
    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    resp = await client.get("/admin", headers=AUTH)
    assert resp.status_code == 200
    assert "1 account" in resp.text or "alice@example.com" in resp.text


async def test_accounts_page_add_and_list(client, admin_ready):
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        resp = await client.post(
            "/admin/accounts/save",
            data={"email": "Alice@Example.com", "targets": ["mobile_app_x"]},
            headers=AUTH,
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert await accounts.get_targets(db.get_db(), "alice@example.com") == ["mobile_app_x"]

    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        page = await client.get("/admin/accounts", headers=AUTH)
    assert "alice@example.com" in page.text


async def test_devices_page_shows_passwordless_cross_reference(client, admin_ready):
    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    with patch("app.routers.admin.devices.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.routers.admin.devices.zitadel_client.list_users", AsyncMock(return_value=FAKE_ZITADEL_USERS)), \
         patch("app.routers.admin.devices.zitadel_client.get_user_ha_targets", AsyncMock(return_value=[])):
        resp = await client.get("/admin/devices", headers=AUTH)
    assert resp.status_code == 200
    assert "Has a passwordless account too: yes" in resp.text


async def test_devices_save(client, admin_ready):
    with patch("app.routers.admin.devices.zitadel_client.set_user_ha_targets", AsyncMock()) as save_mock:
        resp = await client.post(
            "/admin/devices/save",
            data={"user_id": "u1", "targets": ["mobile_app_x"]},
            headers=AUTH,
            follow_redirects=False,
        )
    assert resp.status_code == 303
    save_mock.assert_called_once_with("u1", ["mobile_app_x"])


async def test_audit_page_lists_events(client, admin_ready):
    from app import audit as audit_log

    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    await audit_log.log_event(db.get_db(), "alice@example.com", "req-1", "approved", ip="1.2.3.4")

    resp = await client.get("/admin/audit?account_id=alice@example.com", headers=AUTH)
    assert resp.status_code == 200
    assert "approved" in resp.text
    assert "1.2.3.4" in resp.text


async def test_recovery_generate_shows_codes_once(client, admin_ready):
    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    resp = await client.post("/admin/recovery/generate", data={"email": "alice@example.com"}, headers=AUTH)
    assert resp.status_code == 200
    assert "New codes for alice@example.com" in resp.text


async def test_recovery_regenerate_invalidates_previous_batch(client, admin_ready):
    from app import recovery_codes

    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    first_batch = await recovery_codes.generate_batch(db.get_db(), "alice@example.com", generated_by="admin")
    await client.post("/admin/recovery/generate", data={"email": "alice@example.com"}, headers=AUTH)

    assert await recovery_codes.verify_code(db.get_db(), "alice@example.com", first_batch[0], used_ip="1.2.3.4") is False


async def test_blocked_ips_list_and_unblock(client, admin_ready):
    from app import ip_blocking

    for _ in range(3):
        await ip_blocking.record_failure(db.get_db(), "alice@example.com", "203.0.113.5")
    assert await ip_blocking.is_blocked(db.get_db(), "alice@example.com", "203.0.113.5") is True

    resp = await client.get("/admin/blocked-ips", headers=AUTH)
    assert "203.0.113.5" in resp.text

    unblock_resp = await client.post(
        "/admin/blocked-ips/unblock",
        data={"account_id": "alice@example.com", "ip": "203.0.113.5"},
        headers=AUTH,
        follow_redirects=False,
    )
    assert unblock_resp.status_code == 303
    assert await ip_blocking.is_blocked(db.get_db(), "alice@example.com", "203.0.113.5") is False


async def test_branding_save_and_reload(client, admin_ready):
    resp = await client.post("/admin/branding/save", data={"title": "My Login"}, headers=AUTH, follow_redirects=False)
    assert resp.status_code == 303

    page = await client.get("/admin/branding", headers=AUTH)
    assert 'value="My Login"' in page.text
