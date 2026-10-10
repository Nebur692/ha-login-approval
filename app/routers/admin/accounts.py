"""Manage the generic passwordless-flow account directory (email -> HA
devices) — independent of any relying party (ZITADEL, Keycloak, Authentik,
...). Unlike devices.py (ZITADEL-specific, only registered when ZITADEL is
configured), this page always exists: it's the only account model
routers/idp.py actually uses."""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import accounts, admin_sessions, client_ip, ha_client
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/accounts")
async def accounts_page(request: Request, _: str = Depends(require_admin)):
    # The device list comes from Home Assistant; the accounts do not. With HA
    # away the accounts are still shown, read-only: a form without the device
    # checkboxes would save every account with no devices at all.
    try:
        all_targets = await ha_client.get_notify_targets()
        ha_reachable = True
    except Exception as exc:
        logger.warning("Could not list Home Assistant devices for the accounts page: %s", exc)
        all_targets = []
        ha_reachable = False
    mobile_targets = [t for t in all_targets if t.startswith("mobile_app_")]
    rows = await accounts.list_accounts(get_db())

    return templates.TemplateResponse(request, "admin/accounts.html", {
        "active": "accounts",
        "mobile_targets": mobile_targets,
        "ha_reachable": ha_reachable,
        "rows": rows,
    })


@router.post("/admin/accounts/save")
async def save_account(
    request: Request,
    email: str = Form(...),
    targets: list[str] = Form(default=[]),
    admin_user: str = Depends(require_admin),
):
    await accounts.set_targets(get_db(), email, targets)
    await admin_sessions.record(
        "account_saved", username=admin_user, ip=client_ip.resolve(request),
        detail=f"{email.strip().lower()}: {', '.join(targets) or 'no devices'}",
    )
    return RedirectResponse(url="/admin/accounts", status_code=303)
