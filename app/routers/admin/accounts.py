"""Manage the generic passwordless-flow account directory (email -> HA
devices) — independent of any relying party (ZITADEL, Keycloak, Authentik,
...). Unlike devices.py (ZITADEL-specific, only registered when ZITADEL is
configured), this page always exists: it's the only account model
routers/idp.py actually uses."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import accounts, ha_client
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


@router.get("/admin/accounts")
async def accounts_page(request: Request, _: str = Depends(require_admin)):
    all_targets = await ha_client.get_notify_targets()
    mobile_targets = [t for t in all_targets if t.startswith("mobile_app_")]
    rows = await accounts.list_accounts(get_db())

    return templates.TemplateResponse(request, "admin/accounts.html", {
        "active": "accounts",
        "mobile_targets": mobile_targets,
        "rows": rows,
    })


@router.post("/admin/accounts/save")
async def save_account(
    email: str = Form(...),
    targets: list[str] = Form(default=[]),
    _: str = Depends(require_admin),
):
    await accounts.set_targets(get_db(), email, targets)
    return RedirectResponse(url="/admin/accounts", status_code=303)
