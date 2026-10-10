"""Aggregates every /admin/* sub-router under one `router` — main.py just
does `app.include_router(admin.router)`.
"""
from fastapi import APIRouter

from app.routers.admin import accounts, activity, audit, blocked_ips, branding, home, login, recovery, signing_key

router = APIRouter()
router.include_router(home.router)
router.include_router(accounts.router)
router.include_router(audit.router)
router.include_router(recovery.router)
router.include_router(blocked_ips.router)
router.include_router(branding.router)
router.include_router(signing_key.router)
router.include_router(activity.router)
router.include_router(login.router)
