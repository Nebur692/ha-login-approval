"""Admin dashboard: at-a-glance counts before diving into any specific
section — accounts, devices assigned, recovery codes remaining, IPs
currently blocked. Reports on the generic passwordless account directory
(accounts.py), independent of ZITADEL/Keycloak/Authentik/whatever RP."""
from fastapi import APIRouter, Depends, Request

from app import accounts, ip_blocking, recovery_codes
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


@router.get("/admin")
async def home_page(request: Request, _: str = Depends(require_admin)):
    db = get_db()
    all_accounts = await accounts.list_accounts(db)

    accounts_with_devices = sum(1 for a in all_accounts if a["targets"])
    recovery_summary = []
    for a in all_accounts:
        remaining = await recovery_codes.remaining_count(db, a["email"])
        if remaining:
            recovery_summary.append({"display_name": a["email"], "remaining": remaining})

    blocked = await ip_blocking.list_blocked(db)

    return templates.TemplateResponse(request, "admin/home.html", {
        "active": "home",
        "total_accounts": len(all_accounts),
        "accounts_with_devices": accounts_with_devices,
        "recovery_summary": recovery_summary,
        "blocked_count": len(blocked),
    })
