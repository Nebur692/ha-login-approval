import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch

SIGNING_KEY = "test-signing-key"


def _signed_request(body_dict: dict) -> tuple[bytes, dict]:
    body = json.dumps(body_dict).encode()
    ts = int(time.time())
    digest = hmac.new(SIGNING_KEY.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    headers = {"content-type": "application/json", "zitadel-signature": f"t={ts},v1={digest}"}
    return body, headers


def _payload(user_id: str | None) -> dict:
    checks = {"user": {"userId": user_id}} if user_id else {}
    return {
        "fullMethod": "/zitadel.session.v2.SessionService/CreateSession",
        "request": {
            "checks": checks,
            "userAgent": {"description": "Edge, mobile, Android", "ip": "203.0.113.5"},
        },
    }


async def test_invalid_signature_rejected(client):
    body, headers = _signed_request(_payload("u1"))
    headers["zitadel-signature"] = "t=123,v1=deadbeef"
    resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 401


async def test_no_user_id_passes_through(client):
    body, headers = _signed_request(_payload(None))
    resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_no_targets_configured_passes_through(client):
    body, headers = _signed_request(_payload("u1"))
    with patch("app.routers.webhook.zitadel_client.get_user_ha_targets", AsyncMock(return_value=[])):
        resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_approved_login_passes(client):
    body, headers = _signed_request(_payload("u1"))
    with patch("app.routers.webhook.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.routers.webhook.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.routers.webhook.ha_client.send_approval_notification", AsyncMock()), \
         patch("app.routers.webhook.ha_client.wait_for_action", AsyncMock(return_value=True)):
        resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_notification_uses_detected_language_and_login_details(client):
    body, headers = _signed_request(_payload("u1"))
    mock_send = AsyncMock()
    with patch("app.routers.webhook.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.routers.webhook.ha_client.get_ha_language", AsyncMock(return_value="es")), \
         patch("app.routers.webhook.ha_client.send_approval_notification", mock_send), \
         patch("app.routers.webhook.ha_client.wait_for_action", AsyncMock(return_value=True)):
        await client.post("/webhook/create-session", content=body, headers=headers)

    call_args = mock_send.call_args.args
    assert call_args[0] == "mobile_app_x"
    assert call_args[2] == "Intento de inicio de sesión"  # Spanish title, not bilingual
    assert "203.0.113.5" in call_args[3]  # IP from the login attempt
    assert call_args[4] == "Aprobar"
    assert call_args[5] == "Rechazar"


async def test_rejected_login_blocks(client):
    body, headers = _signed_request(_payload("u1"))
    with patch("app.routers.webhook.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.routers.webhook.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.routers.webhook.ha_client.send_approval_notification", AsyncMock()), \
         patch("app.routers.webhook.ha_client.wait_for_action", AsyncMock(return_value=False)):
        resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 403


async def test_timeout_blocks(client):
    body, headers = _signed_request(_payload("u1"))
    with patch("app.routers.webhook.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.routers.webhook.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.routers.webhook.ha_client.send_approval_notification", AsyncMock()), \
         patch("app.routers.webhook.ha_client.wait_for_action", AsyncMock(return_value=None)):
        resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 403


async def test_notification_send_failure_does_not_crash_the_hook(client):
    """If HA is briefly unreachable for one target, still wait for the
    other target(s)/timeout instead of raising an unhandled exception."""
    body, headers = _signed_request(_payload("u1"))
    with patch("app.routers.webhook.zitadel_client.get_user_ha_targets", AsyncMock(return_value=["mobile_app_x"])), \
         patch("app.routers.webhook.ha_client.get_ha_language", AsyncMock(return_value="en")), \
         patch("app.routers.webhook.ha_client.send_approval_notification", AsyncMock(side_effect=Exception("boom"))), \
         patch("app.routers.webhook.ha_client.wait_for_action", AsyncMock(return_value=None)):
        resp = await client.post("/webhook/create-session", content=body, headers=headers)
    assert resp.status_code == 403
