"""Core of the approval flow: send the actionable HA notification(s) to an
already-resolved list of targets, and wait for a response.

Takes `targets` already resolved rather than looking them up itself — the
caller (routers/idp.py, via accounts.py) decides what "no targets assigned"
means before ever calling this, since this module has no opinion on
account resolution at all.
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
