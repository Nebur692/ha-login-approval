"""Per-account device assignment for the LEGACY Actions V2 webhook
(routers/webhook.py, v1.0.0) — which HA notify.* targets receive the
approve/reject notification sent *before* ZITADEL checks the password.
Only registered when ZITADEL is configured (see main.py); inherently
ZITADEL-specific, since Actions V2 has no equivalent elsewhere.

Also shows whether each ZITADEL account's email has a passwordless account
configured too (app/accounts.py, used by the separate, RP-agnostic
routers/idp.py flow) — the two systems are independent, this is just a
convenience cross-reference to catch a mismatch: someone with the legacy
webhook set up but no passwordless account (or vice versa)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import accounts, ha_client, zitadel_client
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


@router.get("/admin/devices")
async def devices_page(request: Request, _: str = Depends(require_admin)):
    all_targets = await ha_client.get_notify_targets()
    mobile_targets = [t for t in all_targets if t.startswith("mobile_app_")]

    users = await zitadel_client.list_users()
    human_users = [u for u in users if not u["is_machine"]]

    db = get_db()
    rows = []
    for u in human_users:
        current = await zitadel_client.get_user_ha_targets(u["id"])
        has_passwordless_account = bool(u["email"]) and await accounts.account_exists(db, u["email"])
        rows.append({**u, "current_targets": set(current), "has_passwordless_account": has_passwordless_account})

    return templates.TemplateResponse(request, "admin/devices.html", {
        "active": "devices",
        "mobile_targets": mobile_targets,
        "rows": rows,
    })


@router.post("/admin/devices/save")
async def save_targets(
    user_id: str = Form(...),
    targets: list[str] = Form(default=[]),
    _: str = Depends(require_admin),
):
    await zitadel_client.set_user_ha_targets(user_id, targets)
    return RedirectResponse(url="/admin/devices", status_code=303)
