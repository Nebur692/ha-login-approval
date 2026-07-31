import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app import accounts, db, idp_jwt
from app.approval_flow import ApprovalOutcome
from app.config import settings
from app.routers import idp as idp_router

CLIENT_ID = "test-rp"
CLIENT_SECRET = "test-rp-secret"
REDIRECT_URI = "https://rp.test/idps/callback"
EMAIL = "test@example.com"


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


async def test_authorize_bridge_page_has_mobile_viewport_meta(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in resp.text


async def _set_branding(**fields):
    now = "2026-01-01T00:00:00+00:00"
    await db.get_db().execute(
        "INSERT INTO bridge_branding (id, title, logo_path, background_path, favicon_path, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (fields.get("title"), fields.get("logo_path"), fields.get("background_path"), fields.get("favicon_path"), now),
    )
    await db.get_db().commit()


async def test_authorize_renders_custom_title_and_favicon_link(client, idp_ready, tmp_path):
    favicon = tmp_path / "favicon.png"
    favicon.write_bytes(b"fake-png-bytes")
    await _set_branding(title="My Custom Login", favicon_path=str(favicon))

    resp = await client.get("/authorize", params=_authorize_params())

    assert "<title>My Custom Login</title>" in resp.text
    assert '<link rel="icon" href="/branding/favicon">' in resp.text
    assert "<h1>My Custom Login</h1>" in resp.text


async def test_authorize_falls_back_to_default_title_without_branding(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    assert '<link rel="icon"' not in resp.text
    assert "<h1>" not in resp.text


async def test_branding_asset_route_serves_the_stored_file(client, idp_ready, tmp_path):
    favicon = tmp_path / "favicon.png"
    favicon.write_bytes(b"fake-png-bytes")
    await _set_branding(favicon_path=str(favicon))

    resp = await client.get("/branding/favicon")

    assert resp.status_code == 200
    assert resp.content == b"fake-png-bytes"
    assert resp.headers["content-type"] == "image/png"


async def test_branding_asset_route_404_when_not_configured(client, idp_ready):
    resp = await client.get("/branding/favicon")
    assert resp.status_code == 404


async def test_branding_asset_route_404_for_unknown_kind(client, idp_ready):
    resp = await client.get("/branding/nonsense")
    assert resp.status_code == 404


async def test_authorize_defaults_to_english(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    assert '<html lang="en">' in resp.text
    assert "Enter your email to continue." in resp.text


async def test_authorize_detects_spanish_from_accept_language(client, idp_ready):
    resp = await client.get(
        "/authorize", params=_authorize_params(), headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
    )
    assert '<html lang="es">' in resp.text
    assert "Escribe tu email para continuar." in resp.text


async def test_authorize_non_spanish_accept_language_defaults_to_english(client, idp_ready):
    resp = await client.get(
        "/authorize", params=_authorize_params(), headers={"Accept-Language": "fr-FR,fr;q=0.9"},
    )
    assert '<html lang="en">' in resp.text


async def test_authorize_bridge_page_includes_countdown_constant(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    assert f"RECOVERY_DELAY_SECONDS = {settings.bridge_recovery_unlock_delay_seconds};" in resp.text
    assert 'id="countdown"' in resp.text


async def test_status_endpoint_exposes_waiting_since_for_the_countdown(client, idp_ready):
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    data = (await client.get(f"/idp/status/{request_id}")).json()
    assert isinstance(data["waiting_since"], float)


async def test_status_endpoint_waiting_since_is_null_before_notifying(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    assert resp.status_code == 200

    data = (await client.get(f"/idp/status/{request_id}")).json()
    assert data["waiting_since"] is None


async def test_authorize_trusts_x_forwarded_for_over_socket_peer(client, idp_ready):
    resp = await client.get(
        "/authorize",
        params=_authorize_params(),
        headers={"x-forwarded-for": "203.0.113.7, 192.168.100.22"},
    )
    request_id = idp_router._pending.copy().popitem()[0]
    assert resp.status_code == 200
    assert idp_router._pending[request_id]["ip"] == "203.0.113.7"


async def test_discovery_document(client, idp_ready):
    resp = await client.get("/.well-known/openid-configuration")
    assert resp.status_code == 200
    data = resp.json()
    assert data["issuer"] == "http://ha-login.test"
    assert data["userinfo_endpoint"] == "http://ha-login.test/userinfo"


async def test_full_flow_approved_issues_valid_id_token(client, idp_ready):
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])

    authorize_resp = await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    assert authorize_resp.status_code == 200

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)):
        email_resp = await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
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
    assert claims["sub"] == EMAIL
    assert claims["email"] == EMAIL
    assert claims["aud"] == CLIENT_ID
    assert claims["iss"] == "http://ha-login.test"

    userinfo_resp = await client.get("/userinfo", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert userinfo_resp.status_code == 200
    assert userinfo_resp.json()["sub"] == EMAIL

    # Real cryptographic round-trip, not just a structural claims check:
    # the public key JWKS actually serves must validate this exact
    # signature, matching what a real RP does before trusting the token.
    import jwt as pyjwt
    from jwt import PyJWK

    jwks_resp = await client.get("/jwks.json")
    assert jwks_resp.status_code == 200
    jwk = jwks_resp.json()["keys"][0]
    assert jwk["kid"] == pyjwt.get_unverified_header(body["id_token"])["kid"]

    public_key = PyJWK.from_dict(jwk).key
    verified_claims = pyjwt.decode(
        body["id_token"], key=public_key, algorithms=["RS256"],
        audience=CLIENT_ID, issuer="http://ha-login.test",
    )
    assert verified_claims["sub"] == EMAIL


async def test_unknown_email_is_denied(client, idp_ready):
    """No account row at all for this email — accounts.get_targets()
    returns [] just like an account with no devices assigned."""
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    await client.post("/idp/email", data={"request_id": request_id, "email": "nobody@example.com"})
    await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "denied"


async def test_no_targets_denies_passwordless_login(client, idp_ready):
    """An account exists but has no devices assigned — must still deny,
    since there's no password fallback in this flow."""
    await accounts.set_targets(db.get_db(), EMAIL, [])

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
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


# --- Fase 6: recovery/retry gate ------------------------------------------

def test_recovery_unavailable_without_resolved_account():
    pending = {"account_id": None, "status": "waiting", "waiting_since": time.time() - 1000}
    assert idp_router._recovery_available(pending) is False


def test_recovery_available_on_send_failed_regardless_of_elapsed_time():
    pending = {"account_id": EMAIL, "status": "send_failed", "waiting_since": time.time()}
    assert idp_router._recovery_available(pending) is True


def test_recovery_unavailable_before_delay_elapses(monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 60)
    pending = {"account_id": EMAIL, "status": "waiting", "waiting_since": time.time()}
    assert idp_router._recovery_available(pending) is False


def test_recovery_available_after_delay_elapses(monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 60)
    pending = {"account_id": EMAIL, "status": "waiting", "waiting_since": time.time() - 61}
    assert idp_router._recovery_available(pending) is True


async def test_recovery_gate_enforced_on_submit_even_if_client_skips_ui(client, idp_ready):
    """Directly POSTing to /idp/recovery right after /authorize — never
    having gone through the email/notification step — must be rejected.
    The gate is enforced server-side, not just hidden in the UI."""
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    resp = await client.post("/idp/recovery", data={"request_id": request_id, "code": "AAAA-AAAA-AAAA"})
    assert resp.status_code == 403


async def test_retry_not_available_before_gate(client, idp_ready):
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    resp = await client.post("/idp/retry", data={"request_id": request_id})
    assert resp.status_code == 403


async def test_send_failed_makes_recovery_immediately_available(client, idp_ready):
    """Even with the default (non-zero) unlock delay, SEND_FAILED unlocks
    recovery right away — no point waiting out a timer for a notification
    that was never delivered."""
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.SEND_FAILED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "send_failed"
    assert status_resp.json()["recovery_available"] is True


async def test_recovery_flow_survives_a_failure_fetching_ha_language(client, idp_ready, monkeypatch):
    """The low-recovery-codes warning is best-effort — if HA is
    unreachable when fetching its configured language, a valid recovery
    code must still complete the login instead of turning into a 500."""
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    with patch("app.routers.idp.recovery_codes.verify_code", AsyncMock(return_value=True)), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(side_effect=RuntimeError("HA unreachable"))):
        resp = await client.post("/idp/recovery", data={"request_id": request_id, "code": "AAAA-AAAA-AAAA"})

    assert resp.status_code == 200


async def test_recovery_code_completes_login_after_timeout(client, idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "timeout"
    assert status_resp.json()["recovery_available"] is True

    with patch("app.routers.idp.recovery_codes.verify_code", AsyncMock(return_value=True)), \
         patch("app.routers.idp.ha_client.call_service", AsyncMock()), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
        recovery_resp = await client.post("/idp/recovery", data={"request_id": request_id, "code": "AAAA-AAAA-AAAA"})
    assert recovery_resp.status_code == 200

    complete_resp = await client.get(f"/idp/complete/{request_id}", follow_redirects=False)
    assert complete_resp.status_code == 302


async def test_recovery_code_wrong_code_rejected(client, idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    with patch("app.routers.idp.recovery_codes.verify_code", AsyncMock(return_value=False)):
        resp = await client.post("/idp/recovery", data={"request_id": request_id, "code": "WRONG-CODE-HERE"})
    assert resp.status_code == 401


async def test_retry_resends_notification(client, idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    run_approval_mock = AsyncMock(return_value=ApprovalOutcome.APPROVED)
    with patch("app.routers.idp.run_approval", run_approval_mock):
        retry_resp = await client.post("/idp/retry", data={"request_id": request_id})
        assert retry_resp.status_code == 200
        await asyncio.sleep(0.05)

    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "approved"
    run_approval_mock.assert_called_once()


async def test_retry_rejected_once_already_approved(client, idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    resp = await client.post("/idp/retry", data={"request_id": request_id})
    assert resp.status_code == 409


# --- Fase 8: anti-abuse wiring --------------------------------------------

async def test_blocked_ip_denies_without_notifying(client, idp_ready):
    from app import ip_blocking

    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    for _ in range(3):
        await ip_blocking.record_failure(db.get_db(), EMAIL, "127.0.0.1")
    assert await ip_blocking.is_blocked(db.get_db(), EMAIL, "127.0.0.1") is True

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    run_approval_mock = AsyncMock(return_value=ApprovalOutcome.APPROVED)
    with patch("app.routers.idp.run_approval", run_approval_mock):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    run_approval_mock.assert_not_called()
    status_resp = await client.get(f"/idp/status/{request_id}")
    assert status_resp.json()["status"] == "denied"


async def test_explicit_reject_records_ip_failure_and_audit(client, idp_ready):
    from app import audit, ip_blocking

    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.REJECTED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    row = await ip_blocking._get_state(db.get_db(), EMAIL, "127.0.0.1")
    assert row["consecutive_failures"] == 1

    events = await audit.list_events(db.get_db(), EMAIL)
    assert events[0]["event_type"] == "rejected"


async def test_timeout_does_not_record_ip_failure(client, idp_ready):
    from app import ip_blocking

    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    row = await ip_blocking._get_state(db.get_db(), EMAIL, "127.0.0.1")
    assert row is None


async def test_approved_resets_ip_failure_counter(client, idp_ready):
    from app import ip_blocking

    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await ip_blocking.record_failure(db.get_db(), EMAIL, "127.0.0.1")
    await ip_blocking.record_failure(db.get_db(), EMAIL, "127.0.0.1")

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    row = await ip_blocking._get_state(db.get_db(), EMAIL, "127.0.0.1")
    assert row["consecutive_failures"] == 0


async def test_wrong_recovery_code_records_ip_failure(client, idp_ready, monkeypatch):
    from app import ip_blocking

    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    with patch("app.routers.idp.recovery_codes.verify_code", AsyncMock(return_value=False)):
        await client.post("/idp/recovery", data={"request_id": request_id, "code": "WRONG-CODE-HERE"})

    row = await ip_blocking._get_state(db.get_db(), EMAIL, "127.0.0.1")
    assert row["consecutive_failures"] == 1


async def test_correct_recovery_code_logs_audit_and_resets_counter(client, idp_ready, monkeypatch):
    from app import audit, ip_blocking

    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await ip_blocking.record_failure(db.get_db(), EMAIL, "127.0.0.1")

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    with patch("app.routers.idp.recovery_codes.verify_code", AsyncMock(return_value=True)), \
         patch("app.routers.idp.ha_client.call_service", AsyncMock()), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
        resp = await client.post("/idp/recovery", data={"request_id": request_id, "code": "AAAA-AAAA-AAAA"})
    assert resp.status_code == 200

    row = await ip_blocking._get_state(db.get_db(), EMAIL, "127.0.0.1")
    assert row["consecutive_failures"] == 0

    events = await audit.list_events(db.get_db(), EMAIL)
    assert events[0]["event_type"] == "recovery_code_used"


async def test_low_recovery_codes_triggers_warning_notification(client, idp_ready, monkeypatch):
    from app import recovery_codes

    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    monkeypatch.setattr(settings, "recovery_code_low_warning", 3)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    codes = await recovery_codes.generate_batch(db.get_db(), EMAIL, generated_by="admin", count=3)
    # Use 2 of 3 up front so only 1 remains after the one used via the flow below.
    await recovery_codes.verify_code(db.get_db(), EMAIL, codes[0], used_ip="1.2.3.4")
    await recovery_codes.verify_code(db.get_db(), EMAIL, codes[1], used_ip="1.2.3.4")

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock = AsyncMock()
    with patch("app.routers.idp.ha_client.call_service", call_mock), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
        await client.post("/idp/recovery", data={"request_id": request_id, "code": codes[2]})

    call_mock.assert_called_once()
    args = call_mock.call_args.args
    assert args[0] == "notify"
    assert args[1] == "mobile_app_x"
    assert "exhausted" in args[2]["title"].lower()


async def test_low_recovery_codes_warning_at_threshold_not_exhausted(client, idp_ready, monkeypatch):
    """Distinct, less prominent treatment than exhausting the last code —
    e.g. 4 generated, 1 used up front, 1 used via the flow below leaves 2,
    still above zero but at/under the low-warning threshold."""
    from app import recovery_codes

    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    monkeypatch.setattr(settings, "recovery_code_low_warning", 3)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    codes = await recovery_codes.generate_batch(db.get_db(), EMAIL, generated_by="admin", count=4)
    await recovery_codes.verify_code(db.get_db(), EMAIL, codes[0], used_ip="1.2.3.4")

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock = AsyncMock()
    with patch("app.routers.idp.ha_client.call_service", call_mock), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
        await client.post("/idp/recovery", data={"request_id": request_id, "code": codes[1]})

    call_mock.assert_called_once()
    args = call_mock.call_args.args
    assert "exhausted" not in args[2]["title"].lower()
    assert "2" in args[2]["message"]


async def test_no_warning_when_codes_well_above_threshold(client, idp_ready, monkeypatch):
    from app import recovery_codes

    monkeypatch.setattr(settings, "bridge_recovery_unlock_delay_seconds", 0)
    monkeypatch.setattr(settings, "recovery_code_low_warning", 3)
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    codes = await recovery_codes.generate_batch(db.get_db(), EMAIL, generated_by="admin", count=10)

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.TIMEOUT)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock = AsyncMock()
    with patch("app.routers.idp.ha_client.call_service", call_mock):
        await client.post("/idp/recovery", data={"request_id": request_id, "code": codes[0]})

    call_mock.assert_not_called()


async def test_normal_approved_login_warns_when_no_recovery_codes_were_ever_generated(client, idp_ready):
    """An account that never generated a batch at all (remaining_count ==
    0 from day one, not from using them all through the recovery flow)
    would otherwise never be warned — the recovery flow's warning only
    ever fires as a side effect of consuming a code, and there's nothing
    to consume here."""
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    call_mock = AsyncMock()
    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)), \
         patch("app.routers.idp.ha_client.call_service", call_mock), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock.assert_called_once()
    args = call_mock.call_args.args
    assert args[0] == "notify"
    assert args[1] == "mobile_app_x"
    # Reported from production: this used to say "you've just used your last
    # recovery code" to an account that had never generated a batch at all.
    assert args[2]["title"] == "No recovery codes"
    assert "used" not in args[2]["message"].lower()


async def test_exhausted_batch_on_normal_login_is_worded_as_run_out_not_just_used(client, idp_ready):
    """Distinct from never having generated any: here a batch existed and
    was fully consumed earlier, so the account really is out of codes —
    but the code was not "just" used, this is an ordinary login."""
    from app import recovery_codes

    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    codes = await recovery_codes.generate_batch(db.get_db(), EMAIL, generated_by="admin", count=1)
    await recovery_codes.verify_code(db.get_db(), EMAIL, codes[0], used_ip="1.2.3.4")

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    call_mock = AsyncMock()
    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)), \
         patch("app.routers.idp.ha_client.call_service", call_mock), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="en")):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock.assert_called_once()
    args = call_mock.call_args.args
    assert args[2]["title"] == "Recovery codes exhausted"
    assert "just used" not in args[2]["message"].lower()


async def test_normal_approved_login_warning_uses_ha_configured_spanish(client, idp_ready):
    """The warning's language follows HA's own configured language (same
    source as the sign-in notification itself), not the browser's — there
    is no browser request by the time this fires from background code."""
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    call_mock = AsyncMock()
    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)), \
         patch("app.routers.idp.ha_client.call_service", call_mock), \
         patch("app.routers.idp.ha_client.get_ha_language", AsyncMock(return_value="es")):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock.assert_called_once()
    args = call_mock.call_args.args
    assert args[2]["title"] == "Sin códigos de recuperación"


async def test_normal_approved_login_no_warning_with_plenty_of_codes(client, idp_ready):
    from app import recovery_codes

    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await recovery_codes.generate_batch(db.get_db(), EMAIL, generated_by="admin", count=10)

    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    call_mock = AsyncMock()
    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)), \
         patch("app.routers.idp.ha_client.call_service", call_mock):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    call_mock.assert_not_called()


# --- /idp/fail: never leave the browser on a dead end --------------------

async def test_fail_redirects_back_with_error_when_denied(client, idp_ready):
    """Unknown email (or no devices assigned) ends up "denied" with no
    recovery option at all — /idp/fail is the only way back in that case."""
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    await client.post("/idp/email", data={"request_id": request_id, "email": "nobody@example.com"})
    await asyncio.sleep(0.05)

    resp = await client.get(f"/idp/fail/{request_id}", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(REDIRECT_URI)
    assert "error=access_denied" in location
    assert "state=xyz" in location
    # Consumed — the request is gone, matching /idp/complete's own behavior.
    assert request_id not in idp_router._pending


async def test_fail_redirects_back_after_explicit_reject(client, idp_ready):
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.REJECTED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    resp = await client.get(f"/idp/fail/{request_id}", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=access_denied" in resp.headers["location"]


async def test_fail_rejected_while_still_waiting(client, idp_ready):
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]
    idp_router._pending[request_id]["status"] = "waiting"

    resp = await client.get(f"/idp/fail/{request_id}")
    assert resp.status_code == 409


async def test_fail_rejected_once_approved(client, idp_ready):
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    resp = await client.get(f"/idp/fail/{request_id}")
    assert resp.status_code == 409


async def test_fail_unknown_request_404(client, idp_ready):
    resp = await client.get("/idp/fail/does-not-exist")
    assert resp.status_code == 404


async def test_purge_removes_expired_pending_but_keeps_fresh(idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "idp_login_timeout_seconds", 300)
    now = time.time()
    idp_router._pending["expired"] = {"created_at": now - 301}
    idp_router._pending["fresh"] = {"created_at": now}

    idp_router._purge_expired_state()

    assert "expired" not in idp_router._pending
    assert "fresh" in idp_router._pending


async def test_purge_removes_expired_auth_codes_but_keeps_fresh(idp_ready, monkeypatch):
    monkeypatch.setattr(settings, "idp_login_timeout_seconds", 300)
    now = time.time()
    idp_router._auth_codes["expired"] = {"issued_at": now - 301}
    idp_router._auth_codes["fresh"] = {"issued_at": now}

    idp_router._purge_expired_state()

    assert "expired" not in idp_router._auth_codes
    assert "fresh" in idp_router._auth_codes


async def test_purge_removes_expired_access_tokens_but_keeps_fresh(idp_ready):
    now = time.time()
    idp_router._access_tokens["expired"] = {"issued_at": now - idp_router._ACCESS_TOKEN_TTL_SECONDS - 1}
    idp_router._access_tokens["fresh"] = {"issued_at": now}

    idp_router._purge_expired_state()

    assert "expired" not in idp_router._access_tokens
    assert "fresh" in idp_router._access_tokens


async def test_full_flow_access_token_survives_purge_immediately_after_issuance(client, idp_ready):
    """Guards against an off-by-something that would purge a token before
    its advertised expires_in has actually elapsed."""
    await accounts.set_targets(db.get_db(), EMAIL, ["mobile_app_x"])
    await client.get("/authorize", params=_authorize_params())
    request_id = idp_router._pending.copy().popitem()[0]

    with patch("app.routers.idp.run_approval", AsyncMock(return_value=ApprovalOutcome.APPROVED)):
        await client.post("/idp/email", data={"request_id": request_id, "email": EMAIL})
        await asyncio.sleep(0.05)

    complete_resp = await client.get(f"/idp/complete/{request_id}", follow_redirects=False)
    code = complete_resp.headers["location"].split("code=")[1].split("&")[0]

    token_resp = await client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        headers={"Authorization": "Basic dGVzdC1ycDp0ZXN0LXJwLXNlY3JldA=="},
    )
    access_token = token_resp.json()["access_token"]

    idp_router._purge_expired_state()

    assert access_token in idp_router._access_tokens


async def test_periodic_cleanup_loop_purges_on_each_tick(idp_ready, monkeypatch):
    idp_router._pending["expired"] = {"created_at": 0}

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(idp_router.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await idp_router._periodic_cleanup_loop()

    assert sleep_calls == [idp_router._CLEANUP_INTERVAL_SECONDS] * 2
    assert "expired" not in idp_router._pending


