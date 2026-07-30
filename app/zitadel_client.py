"""ZITADEL client: OAuth2 client_credentials token caching, user listing,
and per-user metadata read/write (where the HA device mapping lives).

Used only by the legacy Actions V2 webhook (routers/webhook.py, v1.0.0) and
its admin page (routers/admin/devices.py) — both inherently ZITADEL-
specific, since Actions V2 has no equivalent in Keycloak/Authentik/etc. The
passwordless OIDC provider (routers/idp.py, v2.0.0) never imports this
module; it resolves accounts through its own directory (accounts.py)
instead, so it works identically regardless of which RP is in front of it.

Verified live against a real instance before writing this (not guessed):
- POST /management/v1/users/{id}/metadata/{key} with {"value": "<base64>"}
- GET  /management/v1/users/{id}/metadata/{key} -> {"metadata": {"value": "<base64>", ...}}
- POST /management/v1/users/_search with {} -> {"result": [...]}
"""
import base64
import json
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10

_client: httpx.AsyncClient | None = None
_token: str | None = None
_token_expires_at: float = 0.0


def init_client() -> None:
    global _client
    if _client is not None:
        return
    _client = httpx.AsyncClient(base_url=settings.zitadel_base_url.rstrip("/"), timeout=HTTP_TIMEOUT)


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _require_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("ZITADEL client not initialized — call init_client() first")
    return _client


async def _get_token() -> str:
    """Client-credentials token, cached until shortly before it expires."""
    global _token, _token_expires_at
    if _token and time.time() < _token_expires_at:
        return _token

    resp = await _require_client().post(
        "/oauth/v2/token",
        auth=(settings.zitadel_client_id, settings.zitadel_client_secret),
        data={
            "grant_type": "client_credentials",
            "scope": "openid urn:zitadel:iam:org:project:id:zitadel:aud",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    # Refresh 60s before actual expiry to avoid using an about-to-expire token
    _token_expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
    return _token


async def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {await _get_token()}"}


async def validate_connectivity() -> None:
    await _get_token()
    logger.info("ZITADEL connectivity validated.")


async def list_users() -> list[dict]:
    """Returns every user in the org: [{id, username, display_name, email, is_machine}, ...]."""
    resp = await _require_client().post(
        "/management/v1/users/_search",
        headers=await _auth_headers(),
        json={},
    )
    resp.raise_for_status()
    users = []
    for u in resp.json().get("result", []):
        is_machine = "machine" in u
        display_name = u.get("machine", {}).get("name") if is_machine else u.get("human", {}).get("profile", {}).get("displayName")
        users.append({
            "id": u["id"],
            "username": u.get("userName", ""),
            "display_name": display_name or u.get("userName", ""),
            "email": u.get("human", {}).get("email", {}).get("email", ""),
            "is_machine": is_machine,
        })
    return users




async def get_user_ha_targets(user_id: str) -> list[str]:
    """Returns the list of notify.* targets assigned to this user, or []
    if none are configured (== no second factor required for that account)."""
    resp = await _require_client().get(
        f"/management/v1/users/{user_id}/metadata/{settings.metadata_key}",
        headers=await _auth_headers(),
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    value_b64 = resp.json()["metadata"]["value"]
    return json.loads(base64.b64decode(value_b64))


async def set_user_ha_targets(user_id: str, targets: list[str]) -> None:
    """Writes the notify.* target list for a user. An empty list is valid
    and means 'no second factor configured' — same as never having set it."""
    value_b64 = base64.b64encode(json.dumps(targets).encode()).decode()
    resp = await _require_client().post(
        f"/management/v1/users/{user_id}/metadata/{settings.metadata_key}",
        headers=await _auth_headers(),
        json={"value": value_b64},
    )
    resp.raise_for_status()
