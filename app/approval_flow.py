"""Shared core of the approval flow: resolve a ZITADEL user's assigned HA
devices, send the actionable notification(s), and wait for a response.

Used by both the legacy Actions V2 webhook (routers/webhook.py, v1.0.0,
unchanged behavior) and the new passwordless IDP flow (routers/idp.py,
v2.0.0). The only difference between callers is what to do with a
"no devices configured" outcome: the legacy webhook still has a password
check afterward, so it lets the login through; the IDP flow has no password
fallback at all, so it must deny instead.
"""
import logging
from dataclasses import dataclass
from enum import Enum

from app import ha_client, zitadel_client
from app.config import settings
from app.messages import build_notification

logger = logging.getLogger(__name__)


class ApprovalOutcome(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    NO_TARGETS = "no_targets"
    SEND_FAILED = "send_failed"
    """Every target's notification send raised — there's no point waiting
    for a response nobody was ever notified about (the passwordless bridge
    page uses this to skip straight to the retry/recovery screen instead
    of waiting out the full timeout for nothing, see Fase 6)."""


@dataclass
class LoginContext:
    ip: str
    browser_description: str


async def run_approval(zitadel_user_id: str, request_id: str, context: LoginContext) -> ApprovalOutcome:
    targets = await zitadel_client.get_user_ha_targets(zitadel_user_id)
    if not targets:
        return ApprovalOutcome.NO_TARGETS

    lang = await ha_client.get_ha_language()
    text = build_notification(lang, {"description": context.browser_description, "ip": context.ip})

    send_failures = 0
    for target in targets:
        try:
            await ha_client.send_approval_notification(
                target, request_id, text["title"], text["body"], text["approve"], text["reject"],
            )
        except Exception:
            logger.exception("Failed to send approval notification to %s", target)
            send_failures += 1

    if send_failures == len(targets):
        return ApprovalOutcome.SEND_FAILED

    approved = await ha_client.wait_for_action(request_id, timeout=settings.approval_timeout_seconds)
    if approved is True:
        return ApprovalOutcome.APPROVED
    if approved is False:
        return ApprovalOutcome.REJECTED
    return ApprovalOutcome.TIMEOUT
