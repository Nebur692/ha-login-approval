"""Aggregates every /admin/* sub-router under one `router` — main.py just
does `app.include_router(admin.router)`.
"""
from fastapi import APIRouter

from app.routers.admin import accounts, audit, blocked_ips, branding, home, recovery

router = APIRouter()
router.include_router(home.router)
router.include_router(accounts.router)
router.include_router(audit.router)
router.include_router(recovery.router)
router.include_router(blocked_ips.router)
router.include_router(branding.router)
