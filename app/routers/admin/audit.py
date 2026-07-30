"""Per-account login-attempt history for the passwordless flow:
approved/rejected/timeout/recovery code used/send failed, with timestamp,
IP, browser, and (from Fase 4) city/country/ISP. Keyed by the generic
account directory (accounts.py), not any RP's own user IDs."""
from fastapi import APIRouter, Depends, Request

from app import accounts
from app import audit as audit_log
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


@router.get("/admin/audit")
async def audit_page(request: Request, account_id: str | None = None, _: str = Depends(require_admin)):
    db = get_db()
    all_accounts = await accounts.list_accounts(db)

    selected_id = account_id or (all_accounts[0]["email"] if all_accounts else None)
    events = await audit_log.list_events(db, selected_id) if selected_id else []

    return templates.TemplateResponse(request, "admin/audit.html", {
        "active": "audit",
        "accounts": all_accounts,
        "selected_id": selected_id,
        "events": events,
    })
