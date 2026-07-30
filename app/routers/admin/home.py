"""Admin dashboard: at-a-glance counts before diving into any specific
section — accounts, devices assigned, recovery codes remaining, IPs
currently blocked."""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from app import ip_blocking, recovery_codes, zitadel_client
from app.db import get_db
from app.routers.admin._auth import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/admin")
async def home_page(request: Request, _: str = Depends(require_admin)):
    users = await zitadel_client.list_users()
    human_users = [u for u in users if not u["is_machine"]]

    db = get_db()
    accounts_with_devices = 0
    recovery_summary = []
    for u in human_users:
        targets = await zitadel_client.get_user_ha_targets(u["id"])
        if targets:
            accounts_with_devices += 1
        remaining = await recovery_codes.remaining_count(db, u["id"])
        if remaining:
            recovery_summary.append({"display_name": u["display_name"], "remaining": remaining})

    blocked = await ip_blocking.list_blocked(db)

    return templates.TemplateResponse(request, "admin/home.html", {
        "active": "home",
        "total_accounts": len(human_users),
        "accounts_with_devices": accounts_with_devices,
        "recovery_summary": recovery_summary,
        "blocked_count": len(blocked),
    })
