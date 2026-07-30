import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import db, idp_jwt
from app.approval_flow import ApprovalOutcome
from app.config import settings
from app.routers import idp as idp_router

CLIENT_ID = "test-rp"
CLIENT_SECRET = "test-rp-secret"
REDIRECT_URI = "https://rp.test/idps/callback"


@pytest.fixture
async def idp_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "idp.db"))
    monkeypatch.setattr(settings, "idp_issuer_url", "http://ha-login.test")
    monkeypatch.setattr(settings, "idp_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "idp_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "idp_client_redirect_uri", REDIRECT_URI)
    await db.init_db()
    await idp_jwt.ensure_signing_key()
    idp_router._pending.clear()
    idp_router._auth_codes.clear()
    idp_router._access_tokens.clear()
    yield
    await db.close_db()


def _authorize_params(**overrides):
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid",
        "state": "xyz",
    }
    params.update(overrides)
    return params


async def test_authorize_rejects_unknown_client(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params(client_id="someone-else"))
    assert resp.status_code == 400


async def test_authorize_rejects_wrong_redirect_uri(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params(redirect_uri="https://evil.test/x"))
    assert resp.status_code == 400


async def test_authorize_shows_bridge_page(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    assert resp.status_code == 200
    assert "email-form" in resp.text


async def test_discovery_document(client, idp_ready):
    resp = await client.get("/.well-known/openid-configuration")
    assert resp.status_code == 200
    data = resp.json()
    assert data["issuer"] == "http://ha-login.test"
    assert data["userinfo_endpoint"] == "http://ha-login.test/userinfo"


async def test_full_flow_approved_issues_valid_id_token(client, idp_ready):
    authorize_resp = await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    assert authorize_resp.status_code == 200

    fake_user = {"id": "u1", "username": "test@example.com", "email": "test@example.com", "is_machine": False}
    with patch("app.routers.idp.zitadel_client.find_user_by_login", AsyncMock(return_value=fake_user)), \
         patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)):
        email_resp = await client.post("/idp/email", data={"request_id": request_id, "email": "test@example.com"})
        assert email_resp.status_code == 200
        # The email endpoint fires the approval as a background task
        # (asyncio.create_task) so the browser can start polling right
        # away — give it a chance to run to completion before the patches
        # below are torn down.
        await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "approved"

    complete_resp = await client.get(f"/idp/complete/{request_id}", follow_redirects=False)
    assert complete_resp.status_code == 302
    location = complete_resp.headers["location"]
    assert location.startswith(REDIRECT_URI)
    assert "state=xyz" in location
    code = location.split("code=")[1].split("&")[0]

    token_resp = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        headers={"Authorization": "Basic dGVzdC1ycDp0ZXN0LXJwLXNlY3JldA=="},  # test-rp:test-rp-secret
    )
    assert token_resp.status_code == 200
    body = token_resp.json()
    assert "id_token" in body

    import jwt as pyjwt
    claims = pyjwt.decode(body["id_token"], options={"verify_signature": False})
    assert claims["sub"] == "u1"
    assert claims["email"] == "test@example.com"
    assert claims["aud"] == CLIENT_ID
    assert claims["iss"] == "http://ha-login.test"

    userinfo_resp = await client.get("/userinfo", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert userinfo_resp.status_code == 200
    assert userinfo_resp.json()["sub"] == "u1"


async def test_unknown_email_is_denied(client, idp_ready):
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.zitadel_client.find_user_by_login", AsyncMock(return_value=None)):
        await client.post("/idp/email", data={"request_id": request_id, "email": "nobody@example.com"})
        await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "denied"


async def test_no_targets_denies_passwordless_login(client, idp_ready):
    """Unlike the legacy webhook, NO_TARGETS must deny — there's no password
    fallback in this flow."""
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    fake_user = {"id": "u1", "username": "test@example.com", "email": "test@example.com", "is_machine": False}
    with patch("app.routers.idp.zitadel_client.find_user_by_login", AsyncMock(return_value=fake_user)), \
         patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.NO_TARGETS)):
        await client.post("/idp/email", data={"request_id": request_id, "email": "test@example.com"})
        await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "denied"


async def test_complete_before_approval_rejected(client, idp_ready):
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    resp = await client.get(f"/idp/complete/{request_id}")
    assert resp.status_code == 409


async def test_token_wrong_client_secret_rejected(client, idp_ready):
    resp = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": "whatever"},
        headers={"Authorization": "Basic dGVzdC1ycDp3cm9uZw=="},  # test-rp:wrong
    )
    assert resp.status_code == 401


async def test_userinfo_requires_bearer(client, idp_ready):
    resp = await client.get("/userinfo")
    assert resp.status_code == 401
