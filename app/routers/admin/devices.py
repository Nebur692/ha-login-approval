"""Per-account device assignment — which HA notify.* targets receive the
approval notification for each ZITADEL account. This is v1.0.0's original
/admin content; v2.0.0 adds a "Linked to HA" column so the two possible
mismatches are visible at a glance: linked-but-no-device (the passwordless
button would appear in ZITADEL but nothing would ever arrive) and
device-but-not-linked (configured here but inert until the user links
their own account in ZITADEL)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import ha_client, zitadel_client
from app.config import settings
from app.routers.admin._auth import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/admin/devices")
async def devices_page(request: Request, _: str = Depends(require_admin)):
    all_targets = await ha_client.get_notify_targets()
    mobile_targets = [t for t in all_targets if t.startswith("mobile_app_")]

    users = await zitadel_client.list_users()
    human_users = [u for u in users if not u["is_machine"]]

    rows = []
    for u in human_users:
        current = await zitadel_client.get_user_ha_targets(u["id"])
        linked = False
        if settings.zitadel_idp_resource_id:
            linked_ids = await zitadel_client.get_user_linked_idp_ids(u["id"])
            linked = settings.zitadel_idp_resource_id in linked_ids
        rows.append({**u, "current_targets": set(current), "linked": linked})

    return templates.TemplateResponse(request, "admin/devices.html", {
        "active": "devices",
        "mobile_targets": mobile_targets,
        "rows": rows,
        "idp_configured": bool(settings.zitadel_idp_resource_id),
    })


@router.post("/admin/devices/save")
async def save_targets(
    user_id: str = Form(...),
    targets: list[str] = Form(default=[]),
    _: str = Depends(require_admin),
):
    await zitadel_client.set_user_ha_targets(user_id, targets)
    return RedirectResponse(url="/admin/devices", status_code=303)
