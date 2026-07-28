"""Small internal admin panel: pick which HA notify.* targets (devices with
the Companion App) should receive the approval notification for each
ZITADEL account. Protected by HTTP Basic Auth — this is a tiny, low-traffic
internal tool, not worth a full session/cookie system for v1."""
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app import ha_client, zitadel_client
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})


@router.get("/admin")
async def admin_page(request: Request, _: None = Depends(require_admin)):
    all_targets = await ha_client.get_notify_targets()
    mobile_targets = [t for t in all_targets if t.startswith("mobile_app_")]

    users = await zitadel_client.list_users()
    human_users = [u for u in users if not u["is_machine"]]

    rows = []
    for u in human_users:
        current = await zitadel_client.get_user_ha_targets(u["id"])
        rows.append({**u, "current_targets": set(current)})

    return templates.TemplateResponse(request, "admin.html", {
        "mobile_targets": mobile_targets,
        "rows": rows,
    })


@router.post("/admin/save")
async def save_targets(
    user_id: str = Form(...),
    targets: list[str] = Form(default=[]),
    _: None = Depends(require_admin),
):
    await zitadel_client.set_user_ha_targets(user_id, targets)
    return RedirectResponse(url="/admin", status_code=303)
