"""Endpoint ZITADEL calls (as a Request-type Actions V2 target with
interruptOnError=true) right before a session is created — i.e. right
after password/IdP verification succeeds, before the user is actually
logged in. Returning a non-2xx status here aborts the login."""
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app import ha_client, zitadel_client
from app.config import settings
from app.messages import build_notification
from app.zitadel_signature import verify as verify_signature

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/create-session")
async def create_session_hook(
    request: Request,
    zitadel_signature: str | None = Header(default=None),
):
    raw_body = await request.body()
    if not verify_signature(raw_body, zitadel_signature, settings.zitadel_target_signing_key):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    user_id = payload.get("request", {}).get("checks", {}).get("user", {}).get("userId")
    if not user_id:
        # No password/IdP check on this session request (e.g. token refresh) —
        # nothing for us to gate, let it through unchanged.
        return {}

    targets = await zitadel_client.get_user_ha_targets(user_id)
    if not targets:
        # No devices configured for this account — no second factor set up,
        # don't block a login that has nothing to check against.
        return {}

    request_id = ha_client.new_request_id()
    lang = await ha_client.get_ha_language()
    user_agent = payload.get("request", {}).get("userAgent", {})
    text = build_notification(lang, user_agent)

    for target in targets:
        try:
            await ha_client.send_approval_notification(
                target, request_id, text["title"], text["body"], text["approve"], text["reject"],
            )
        except Exception:
            logger.exception("Failed to send approval notification to %s", target)

    approved = await ha_client.wait_for_action(request_id, timeout=settings.approval_timeout_seconds)

    if approved is True:
        return {}
    if approved is False:
        raise HTTPException(status_code=403, detail="Login rejected from Home Assistant")
    raise HTTPException(status_code=403, detail="Login approval timed out")
