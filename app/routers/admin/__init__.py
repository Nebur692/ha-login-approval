"""Aggregates every /admin/* sub-router under one `router` — main.py just
does `app.include_router(admin.router)`, same as before this was split."""
from fastapi import APIRouter

from app.routers.admin import audit, blocked_ips, branding, devices, home, recovery

router = APIRouter()
router.include_router(home.router)
router.include_router(devices.router)
router.include_router(audit.router)
router.include_router(recovery.router)
router.include_router(blocked_ips.router)
router.include_router(branding.router)
