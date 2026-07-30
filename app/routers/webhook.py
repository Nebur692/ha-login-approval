"""Endpoint ZITADEL calls (as a Request-type Actions V2 target with
interruptOnError=true) right before a session is created — i.e. right
after password/IdP verification succeeds, before the user is actually
logged in. Returning a non-2xx status here aborts the login."""
from fastapi import APIRouter, Header, HTTPException, Request

from app import ha_client, zitadel_client
from app.approval_flow import ApprovalOutcome, LoginContext, run_approval
from app.config import settings
from app.zitadel_signature import verify as verify_signature

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

    # ZITADEL-specific resolution (Actions V2 has no equivalent elsewhere,
    # so this legacy flow keeps using zitadel_client directly, unlike the
    # passwordless IDP flow which resolves targets via accounts.py instead).
    targets = await zitadel_client.get_user_ha_targets(user_id)
    if not targets:
        # No second factor configured for this account — this webhook runs
        # *before* the password is checked, so letting it through here
        # doesn't skip authentication, unlike the passwordless IDP flow.
        return {}

    request_id = ha_client.new_request_id()
    user_agent = payload.get("request", {}).get("userAgent", {})
    context = LoginContext(ip=user_agent.get("ip", "unknown"), browser_description=user_agent.get("description", ""))

    outcome = await run_approval(targets, request_id, context)

    if outcome == ApprovalOutcome.APPROVED:
        return {}
    if outcome == ApprovalOutcome.REJECTED:
        raise HTTPException(status_code=403, detail="Login rejected from Home Assistant")
    if outcome == ApprovalOutcome.SEND_FAILED:
        raise HTTPException(status_code=403, detail="Could not reach Home Assistant to request approval")
    raise HTTPException(status_code=403, detail="Login approval timed out")
