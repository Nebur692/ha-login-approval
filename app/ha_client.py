"""Home Assistant client: REST calls + a WebSocket listener dedicated to
actionable-notification button presses (mobile_app_notification_action).

Architecture mirrors app/ha_client.py from the ha-pass-invitations project
(persistent httpx client, reconnecting WS listener with backoff) — this
service only ever cares about one event type, so there's no per-token
entity cache/fan-out like that project needed.
"""
import asyncio
import json
import logging
import uuid
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
import websockets.exceptions

from app.config import settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10
WS_PING_INTERVAL = 30
WS_BACKOFF_INIT = 2
WS_BACKOFF_MAX = 60

_client: httpx.AsyncClient | None = None


def init_client() -> None:
    global _client
    if _client is not None:
        return
    _client = httpx.AsyncClient(
        base_url=settings.ha_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {settings.ha_token}",
            "Content-Type": "application/json",
        },
        timeout=HTTP_TIMEOUT,
    )


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _require_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HA client not initialized — call init_client() first")
    return _client


async def validate_connectivity() -> None:
    resp = await _require_client().get("/api/")
    resp.raise_for_status()
    logger.info("Home Assistant connectivity validated.")


_language_cache: str | None = None


async def get_ha_language() -> str:
    """Returns HA's configured UI language (e.g. 'es', 'en'), fetched once
    and cached for the lifetime of the process — this is an instance-wide
    setting that essentially never changes at runtime."""
    global _language_cache
    if _language_cache is None:
        resp = await _require_client().get("/api/config")
        resp.raise_for_status()
        _language_cache = resp.json().get("language", "en")
    return _language_cache


async def get_notify_targets() -> list[str]:
    """Returns every notify.* service currently registered in HA — one per
    device with the Companion App installed and paired (plus any other
    notify integration, e.g. persistent_notification, which callers should
    filter out if they only want mobile devices — left as-is here since
    admin.py already knows to look for the mobile_app_ prefix)."""
    resp = await _require_client().get("/api/services")
    resp.raise_for_status()
    for domain_block in resp.json():
        if domain_block.get("domain") == "notify":
            return sorted(domain_block.get("services", {}).keys())
    return []


async def call_service(domain: str, service: str, data: dict) -> None:
    resp = await _require_client().post(f"/api/services/{domain}/{service}", json=data)
    resp.raise_for_status()


async def send_approval_notification(
    target: str,
    request_id: str,
    title: str,
    message: str,
    approve_label: str,
    reject_label: str,
) -> None:
    """Sends an actionable notification with Approve/Reject buttons to a
    single notify.* target. The request_id is baked into the action names
    themselves (approve_login_<id> / reject_login_<id>) rather than relying
    on extra action-data fields, since those aren't echoed back reliably on
    every platform — this way correlation only needs string-parsing the
    action name, which every Companion App version already supports."""
    await call_service("notify", target, {
        "title": title,
        "message": message,
        "data": {
            "tag": request_id,
            "actions": [
                {"action": f"approve_login_{request_id}", "title": approve_label},
                {"action": f"reject_login_{request_id}", "title": reject_label},
            ],
            # iOS: shows immediately, overrides Focus modes, no special
            # entitlement needed (unlike "critical", which requires Apple's
            # critical-alerts entitlement and may silently not escalate
            # without it).
            "push": {"interruption-level": "time-sensitive"},
            # Android: a dedicated high-importance channel is what actually
            # makes it a heads-up notification — "push.interruption-level"
            # above is iOS-only and does nothing on Android.
            "channel": "Login Approval",
            "importance": "high",
        },
    })


# ---------------------------------------------------------------------------
# WebSocket listener — subscribes only to mobile_app_notification_action
# ---------------------------------------------------------------------------

_pending: dict[str, asyncio.Future] = {}
_ws_task: asyncio.Task | None = None
_ws_healthy = False


def _build_ws_url() -> str:
    parsed = urlparse(settings.ha_base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(parsed._replace(scheme=scheme)) + "/api/websocket"


def is_ws_healthy() -> bool:
    return _ws_healthy and _ws_task is not None and not _ws_task.done()


async def wait_for_action(request_id: str, timeout: float) -> bool | None:
    """Registers interest in a request_id and waits for the matching
    approve/reject action. Returns True (approved), False (rejected), or
    None if the timeout elapses with no response."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _pending[request_id] = fut
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        _pending.pop(request_id, None)


def _resolve_action(action: str) -> None:
    """Parses an incoming action string and resolves the matching pending
    future, if any is still being waited on."""
    if action.startswith("approve_login_"):
        request_id, approved = action[len("approve_login_"):], True
    elif action.startswith("reject_login_"):
        request_id, approved = action[len("reject_login_"):], False
    else:
        return

    fut = _pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(approved)


async def _ws_listener() -> None:
    global _ws_healthy
    ws_url = _build_ws_url()
    backoff = WS_BACKOFF_INIT
    while True:
        try:
            logger.info("Connecting to HA WebSocket at %s", ws_url)
            async with websockets.connect(ws_url, ping_interval=WS_PING_INTERVAL) as ws:
                backoff = WS_BACKOFF_INIT

                raw = await ws.recv()
                if json.loads(raw).get("type") != "auth_required":
                    continue

                await ws.send(json.dumps({"type": "auth", "access_token": settings.ha_token}))
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("type") != "auth_ok":
                    logger.critical("HA WebSocket auth failed — check HA_TOKEN: %s", msg)
                    _ws_healthy = False
                    return

                await ws.send(json.dumps({
                    "id": 1,
                    "type": "subscribe_events",
                    "event_type": "mobile_app_notification_action",
                }))
                raw = await ws.recv()
                if not json.loads(raw).get("success"):
                    logger.error("HA subscribe failed: %s", raw)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, WS_BACKOFF_MAX)
                    continue

                _ws_healthy = True
                logger.info("HA WebSocket subscribed to mobile_app_notification_action events.")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") != "event":
                        continue
                    action = msg.get("event", {}).get("data", {}).get("action", "")
                    if action:
                        _resolve_action(action)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("HA WebSocket closed, reconnecting in %ds…", backoff)
        except OSError as exc:
            logger.warning("HA WebSocket OSError: %s — reconnecting in %ds…", exc, backoff)
        except Exception:
            logger.exception("HA WebSocket unexpected error — reconnecting in %ds…", backoff)

        _ws_healthy = False
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, WS_BACKOFF_MAX)


async def start_ws_listener() -> None:
    global _ws_task
    _ws_task = asyncio.create_task(_ws_listener())


async def stop_ws_listener() -> None:
    global _ws_task
    if _ws_task:
        _ws_task.cancel()
        try:
            await _ws_task
        except asyncio.CancelledError:
            pass
        _ws_task = None


def new_request_id() -> str:
    return uuid.uuid4().hex
