"""View and manually unblock IPs — the user flagged this as "very
important": an accidental triple-reject or three mistyped recovery codes
shouldn't lock the real account owner out with no way back in."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import ip_blocking
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


@router.get("/admin/blocked-ips")
async def blocked_ips_page(request: Request, _: str = Depends(require_admin)):
    blocked = await ip_blocking.list_blocked(get_db())
    return templates.TemplateResponse(request, "admin/blocked_ips.html", {
        "active": "blocked_ips",
        "blocked": blocked,
    })


@router.post("/admin/blocked-ips/unblock")
async def unblock(
    account_id: str = Form(...),
    ip: str = Form(...),
    admin_user: str = Depends(require_admin),
):
    await ip_blocking.unblock(get_db(), account_id, ip, unblocked_by=admin_user)
    return RedirectResponse(url="/admin/blocked-ips", status_code=303)
