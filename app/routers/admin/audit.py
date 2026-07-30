"""Per-account login-attempt history: approved/rejected/timeout/recovery
code used/send failed, with timestamp, IP, browser, and (from Fase 4)
city/country/ISP."""
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from app import audit as audit_log
from app import zitadel_client
from app.db import get_db
from app.routers.admin._auth import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/admin/audit")
async def audit_page(request: Request, user_id: str | None = None, _: str = Depends(require_admin)):
    users = await zitadel_client.list_users()
    human_users = [u for u in users if not u["is_machine"]]

    selected_id = user_id or (human_users[0]["id"] if human_users else None)
    events = await audit_log.list_events(get_db(), selected_id) if selected_id else []

    return templates.TemplateResponse(request, "admin/audit.html", {
        "active": "audit",
        "users": human_users,
        "selected_id": selected_id,
        "events": events,
    })
