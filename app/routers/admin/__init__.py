"""Aggregates every /admin/* sub-router under one `router` — main.py just
does `app.include_router(admin.router)`, same as before this was split.

`devices` (the legacy per-ZITADEL-account panel for the Actions V2
webhook) is only included when ZITADEL is actually configured — everything
else here operates on the generic, RP-agnostic account directory
(accounts.py) and is always available.
"""
from fastapi import APIRouter

from app.config import settings
from app.routers.admin import accounts, audit, blocked_ips, branding, home, recovery

router = APIRouter()
router.include_router(home.router)
router.include_router(accounts.router)
router.include_router(audit.router)
router.include_router(recovery.router)
router.include_router(blocked_ips.router)
router.include_router(branding.router)

if settings.zitadel_base_url:
    from app.routers.admin import devices
    router.include_router(devices.router)
