"""Which application a login is on its way to, for the approval notification.

The OIDC hop from a broker to this service never says. ZITADEL, Keycloak and
Authentik all forward the browser here with their *own* client_id and
redirect_uri — the app the person actually opened stays on the broker's side
(confirmed against real ZITADEL traffic: no parameter carries it).

The broker does know, though, and ZITADEL can be asked. The `state` it sends
to /authorize is the ID of its IdP intent; that intent records the login
request it belongs to, and the request records the app's client_id and
redirect_uri. Three reads of its event store, all made before the person is
notified, since all three events exist before ZITADEL sends anyone here.

Entirely optional: without ZITADEL credentials `resolve()` returns None and the
notification simply has no app line. Any failure does the same — this is a
nicety on a message, and must never delay or break a login.
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_LOOKUP_TIMEOUT_SECONDS = 3.0
_APPS_REFRESH_MIN_INTERVAL_SECONDS = 60
_MAX_NAME = 80
# ZITADEL IDs are decimal. A `state` that isn't one did not come from ZITADEL,
# so there is nothing to ask it about.
_ZITADEL_ID = re.compile(r"[0-9]{1,32}")
_OIDC_REQUEST_PREFIX = "oidc_"
_APP_EVENT_TYPES = [
    "project.application.added",
    "project.application.changed",
    "project.application.removed",
    "project.application.config.oidc.added",
]


@dataclass(frozen=True)
class TargetApp:
    name: str | None
    host: str | None

    def label(self) -> str | None:
        if self.name and self.host and self.name != self.host:
            return f"{self.name} ({self.host})"
        return self.name or self.host


_token: str | None = None
_token_expires_at = 0.0
_app_names: dict[str, str] = {}
_apps_loaded_at = 0.0
# Tests swap in an httpx.MockTransport that answers like ZITADEL does.
_transport: httpx.AsyncBaseTransport | None = None


def is_configured() -> bool:
    return bool(settings.zitadel_api_url and settings.zitadel_api_client_id and settings.zitadel_api_client_secret)


async def resolve(state: str) -> TargetApp | None:
    if not is_configured() or not _ZITADEL_ID.fullmatch(state or ""):
        return None
    try:
        return await asyncio.wait_for(_resolve_from_zitadel(state), _LOOKUP_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("Could not find out which app this login is for: %s", exc or type(exc).__name__)
        return None


def _base_url() -> str:
    return settings.zitadel_api_url.rstrip("/")


async def _resolve_from_zitadel(state: str) -> TargetApp | None:
    async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT_SECONDS, transport=_transport) as client:
        intent = await _first_event(client, state, "idpintent.started")
        request_id = _request_id_from_intent(intent)
        if request_id is None:
            return None
        auth_request = await _first_event(client, request_id, "auth_request.added")
        if auth_request is None:
            return None
        client_id = auth_request.get("client_id") or auth_request.get("clientId")
        redirect_uri = auth_request.get("redirect_uri") or auth_request.get("redirectUri") or ""
        name = await _app_name(client, client_id) if client_id else None
        host = urlparse(redirect_uri).hostname
        if not name and not host:
            return None
        return TargetApp(name=name, host=host)


def _request_id_from_intent(payload: dict | None) -> str | None:
    """The intent keeps the login request's ID in the query string of the URL
    it returns to. ZITADEL serialises that URL as Go's url.URL struct; a plain
    string is accepted too, in case a later version simplifies it."""
    if not payload:
        return None
    url = payload.get("successURL")
    if isinstance(url, dict):
        query = url.get("RawQuery") or ""
    elif isinstance(url, str):
        query = urlparse(url).query
    else:
        return None
    request_id = (parse_qs(query).get("requestId") or [""])[0]
    # SAML and device-flow requests carry other prefixes and live elsewhere.
    if not request_id.startswith(_OIDC_REQUEST_PREFIX):
        return None
    return request_id[len(_OIDC_REQUEST_PREFIX):] or None


async def _first_event(client: httpx.AsyncClient, aggregate_id: str, event_type: str) -> dict | None:
    events = await _search_events(client, {
        "aggregateId": aggregate_id, "eventTypes": [event_type], "limit": 1, "asc": True,
    })
    return events[0].get("payload") if events else None


async def _app_name(client: httpx.AsyncClient, client_id: str) -> str | None:
    """client_id -> app name, from the project events. Kept in memory and
    reloaded on a miss, so an app created after startup is found too — but not
    more than once a minute, or an unknown client_id would mean a reload per
    login."""
    global _apps_loaded_at
    if client_id not in _app_names and time.monotonic() - _apps_loaded_at > _APPS_REFRESH_MIN_INTERVAL_SECONDS:
        events = await _search_events(client, {
            "aggregateTypes": ["project"], "eventTypes": _APP_EVENT_TYPES, "limit": 1000, "asc": True,
        })
        _app_names.clear()
        _app_names.update(_names_by_client_id(events))
        _apps_loaded_at = time.monotonic()
    return _app_names.get(client_id)


def _names_by_client_id(events: list[dict]) -> dict[str, str]:
    """Replays the app events in order: an app is named when added, may be
    renamed, gets its client_id with its OIDC config, and may be removed."""
    names: dict[str, str] = {}
    client_ids: dict[str, str] = {}
    for event in events:
        kind = (event.get("type") or {}).get("type")
        payload = event.get("payload") or {}
        app_id = payload.get("appId")
        if not app_id:
            continue
        if kind in ("project.application.added", "project.application.changed") and payload.get("name"):
            names[app_id] = payload["name"][:_MAX_NAME]
        elif kind == "project.application.config.oidc.added" and payload.get("clientId"):
            client_ids[app_id] = payload["clientId"]
        elif kind == "project.application.removed":
            names.pop(app_id, None)
            client_ids.pop(app_id, None)
    return {client_id: names[app_id] for app_id, client_id in client_ids.items() if app_id in names}


async def _search_events(client: httpx.AsyncClient, query: dict) -> list[dict]:
    response = await client.post(
        f"{_base_url()}/admin/v1/events/_search",
        json=query,
        headers={"Authorization": f"Bearer {await _access_token(client)}"},
    )
    response.raise_for_status()
    return response.json().get("events") or []


async def _access_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires_at
    if _token and time.monotonic() < _token_expires_at:
        return _token
    response = await client.post(
        f"{_base_url()}/oauth/v2/token",
        data={"grant_type": "client_credentials", "scope": "openid urn:zitadel:iam:org:project:id:zitadel:aud"},
        auth=(settings.zitadel_api_client_id, settings.zitadel_api_client_secret),
    )
    response.raise_for_status()
    body = response.json()
    _token = body["access_token"]
    # Renewed a minute early, so a token never expires between check and use.
    _token_expires_at = time.monotonic() + max(int(body.get("expires_in", 300)) - 60, 30)
    return _token
