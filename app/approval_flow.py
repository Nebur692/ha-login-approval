"""Shared core of the approval flow: send the actionable HA notification(s)
to an already-resolved list of targets, and wait for a response.

Deliberately platform-agnostic — this module never resolves "which account,
which targets" itself, and never imports zitadel_client. That resolution is
each caller's job, because it differs by design: the legacy Actions V2
webhook (routers/webhook.py, v1.0.0) resolves targets via ZITADEL's own
per-user metadata (inherently ZITADEL-specific, Actions V2 has no
equivalent elsewhere); the passwordless OIDC flow (routers/idp.py, v2.0.0)
resolves them via our own account directory (accounts.py), independent of
whichever RP redirected the user here. Both callers already know whether
they got zero targets before ever calling this — what to do about that
differs too (the legacy webhook still has a password afterward, so it lets
the login through; the passwordless flow has no fallback, so it must deny)
and is entirely the caller's decision, not this module's.
"""
import logging
from dataclasses import dataclass
from enum import Enum

from app import ha_client
from app.config import settings
from app.messages import build_notification

logger = logging.getLogger(__name__)


class ApprovalOutcome(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    SEND_FAILED = "send_failed"
    """Every target's notification send raised — there's no point waiting
    for a response nobody was ever notified about (the passwordless bridge
    page uses this to skip straight to the retry/recovery screen instead
    of waiting out the full timeout for nothing, see Fase 6)."""


@dataclass
class LoginContext:
    ip: str
    browser_description: str


async def run_approval(targets: list[str], request_id: str, context: LoginContext) -> ApprovalOutcome:
    """Assumes `targets` is non-empty — callers check for "no devices
    assigned" themselves before calling this, since what to do about it is
    a caller-specific decision (see module docstring)."""
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
