from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import accounts, db
from app.config import settings
from main import app
from tests.conftest import sign_in

PAGES = ["/admin", "/admin/accounts", "/admin/audit", "/admin/recovery", "/admin/blocked-ips",
         "/admin/branding", "/admin/signing-key", "/admin/activity"]
ACTIONS = ["/admin/accounts/save", "/admin/recovery/generate", "/admin/blocked-ips/unblock",
           "/admin/branding/save", "/admin/signing-key/rotate", "/admin/activity/end-session", "/admin/logout"]


@pytest.fixture
async def db_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "admin.db"))
    monkeypatch.setattr(settings, "branding_asset_dir", str(tmp_path / "branding"))
    await db.init_db()
    yield
    await db.close_db()


@pytest.fixture
async def admin_ready(client, db_ready, monkeypatch):
    """Signed in; the value is the session's CSRF token."""
    return await sign_in(client, monkeypatch)


def _admin_routes() -> set[tuple[str, str]]:
    """Every /admin route the app really serves — found by walking the router,
    so a new page cannot be added without the tests below seeing it."""
    found = set()

    def walk(routes):
        for route in routes:
            if hasattr(route, "routes"):
                walk(route.routes)
            for attr in ("original_router", "router"):
                if hasattr(route, attr) and hasattr(getattr(route, attr), "routes"):
                    walk(getattr(route, attr).routes)
            path = getattr(route, "path", "")
            if path.startswith("/admin") and path != "/admin/login":
                for method in getattr(route, "methods", ()):
                    if method != "HEAD":
                        found.add((method, path))
    walk(app.routes)
    return found


def test_the_lists_below_cover_every_admin_route():
    listed = {("GET", p) for p in PAGES} | {("POST", p) for p in ACTIONS}
    assert _admin_routes() == listed


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_sends_a_stranger_to_sign_in(client, db_ready, path):
    resp = await client.get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/login?next={path}"


@pytest.mark.parametrize("path", ACTIONS)
async def test_every_action_refuses_a_stranger(client, db_ready, path):
    resp = await client.post(path, data={"email": "x@example.com"}, follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.parametrize("path", ACTIONS)
async def test_every_action_refuses_a_signed_in_request_without_the_csrf_token(client, admin_ready, path):
    for data in ({"email": "x@example.com"}, {"email": "x@example.com", "csrf_token": "forged"}):
        resp = await client.post(path, data=data, follow_redirects=False)
        assert resp.status_code == 403, data


async def test_home_page_shows_counts(client, admin_ready):
    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    resp = await client.get("/admin")
    assert resp.status_code == 200
    assert "1 account" in resp.text or "alice@example.com" in resp.text


async def test_accounts_page_add_and_list(client, admin_ready):
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        resp = await client.post(
            "/admin/accounts/save",
            data={"email": "Alice@Example.com", "targets": ["mobile_app_x"], "csrf_token": admin_ready},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert await accounts.get_targets(db.get_db(), "alice@example.com") == ["mobile_app_x"]

    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        page = await client.get("/admin/accounts")
    assert "alice@example.com" in page.text


async def test_audit_page_lists_events(client, admin_ready):
    from app import audit as audit_log

    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    await audit_log.log_event(db.get_db(), "alice@example.com", "req-1", "approved", ip="1.2.3.4")

    resp = await client.get("/admin/audit?account_id=alice@example.com")
    assert resp.status_code == 200
    assert "approved" in resp.text
    assert "1.2.3.4" in resp.text


async def test_recovery_generate_shows_codes_once(client, admin_ready):
    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    resp = await client.post("/admin/recovery/generate", data={"email": "alice@example.com", "csrf_token": admin_ready})
    assert resp.status_code == 200
    assert "New codes for alice@example.com" in resp.text


async def test_recovery_regenerate_invalidates_previous_batch(client, admin_ready):
    from app import recovery_codes

    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_x"])
    first_batch = await recovery_codes.generate_batch(db.get_db(), "alice@example.com", generated_by="admin")
    await client.post("/admin/recovery/generate", data={"email": "alice@example.com", "csrf_token": admin_ready})

    assert await recovery_codes.verify_code(db.get_db(), "alice@example.com", first_batch[0], used_ip="1.2.3.4") is False


async def test_blocked_ips_list_and_unblock(client, admin_ready):
    from app import ip_blocking

    for _ in range(3):
        await ip_blocking.record_failure(db.get_db(), "alice@example.com", "203.0.113.5")
    assert await ip_blocking.is_blocked(db.get_db(), "alice@example.com", "203.0.113.5") is True

    resp = await client.get("/admin/blocked-ips")
    assert "203.0.113.5" in resp.text

    unblock_resp = await client.post(
        "/admin/blocked-ips/unblock",
        data={"account_id": "alice@example.com", "ip": "203.0.113.5", "csrf_token": admin_ready},
        follow_redirects=False,
    )
    assert unblock_resp.status_code == 303
    assert await ip_blocking.is_blocked(db.get_db(), "alice@example.com", "203.0.113.5") is False


async def test_branding_save_and_reload(client, admin_ready):
    resp = await client.post("/admin/branding/save", data={"title": "My Login", "csrf_token": admin_ready}, follow_redirects=False)
    assert resp.status_code == 303

    page = await client.get("/admin/branding")
    assert 'value="My Login"' in page.text


async def test_branding_upload_converts_non_standard_format_and_oversized_image(client, admin_ready):
    from io import BytesIO

    from PIL import Image

    # A BMP (non-standard for the web) and way larger than the favicon's
    # 64x64 cap — both should be normalized away, not stored as-is.
    buf = BytesIO()
    Image.new("RGB", (2000, 2000), (10, 20, 30)).save(buf, format="BMP")

    resp = await client.post(
        "/admin/branding/save",
        files={"favicon": ("weird.bmp", buf.getvalue(), "image/bmp")},
        data={"csrf_token": admin_ready},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    saved = Path(settings.branding_asset_dir) / "favicon.png"
    assert saved.exists()
    with Image.open(saved) as img:
        assert img.format == "PNG"
        assert img.size == (64, 64)


async def test_branding_upload_rejects_invalid_image(client, admin_ready):
    resp = await client.post(
        "/admin/branding/save",
        files={"logo": ("not-an-image.png", b"definitely not an image", "image/png")},
        data={"csrf_token": admin_ready},
        follow_redirects=False,
    )
    assert resp.status_code == 400


async def test_accounts_page_still_shows_accounts_when_home_assistant_is_down(client, admin_ready):
    import httpx

    await accounts.set_targets(db.get_db(), "alice@example.com", ["mobile_app_alice", "mobile_app_tablet"])
    await accounts.set_targets(db.get_db(), "bob@example.com", [])
    down = AsyncMock(side_effect=httpx.ConnectError("Name or service not known"))
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", down):
        page = await client.get("/admin/accounts")

    assert page.status_code == 200
    assert "Home Assistant isn't answering" in page.text
    assert "alice@example.com" in page.text and "bob@example.com" in page.text
    assert "mobile_app_alice" in page.text and "mobile_app_tablet" in page.text
    assert "No device assigned." in page.text
    # read-only: a save form here would wipe every account's devices
    assert "/admin/accounts/save" not in page.text


async def test_accounts_page_with_home_assistant_up_has_no_warning(client, admin_ready):
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        page = await client.get("/admin/accounts")
    assert page.status_code == 200
    assert "Home Assistant isn't answering" not in page.text
    assert "/admin/accounts/save" in page.text


TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "admin"


@pytest.mark.parametrize("template", sorted(p.name for p in TEMPLATES.glob("*.html")))
def test_every_post_form_carries_the_csrf_token(template):
    import re

    text = (TEMPLATES / template).read_text()
    for form in re.findall(r"<form\b[^>]*method=\"post\"[^>]*>.*?</form>", text, re.S):
        if 'action="/admin/login"' in form:
            continue  # no session yet to take a token from
        assert 'name="csrf_token" value="{{ request.state.csrf_token }}"' in form, form[:120]
