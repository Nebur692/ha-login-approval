"""What has been done in the admin panel and who is signed in to it — every
sign-in, good or bad, and every change (admin_sessions.py)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import admin_sessions, client_ip
from app.routers.admin._auth import require_admin
from app.routers.admin._templates import templates

router = APIRouter()


@router.get("/admin/activity")
async def activity_page(request: Request, _: str = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/activity.html", {
        "active": "activity",
        "sessions": await admin_sessions.list_sessions(),
        "events": await admin_sessions.list_events(),
    })


@router.post("/admin/activity/end-session")
async def end_session(request: Request, token_hash: str = Form(...), admin_user: str = Depends(require_admin)):
    if await admin_sessions.end(token_hash):
        await admin_sessions.record(
            admin_sessions.SESSION_ENDED, username=admin_user, ip=client_ip.resolve(request),
            detail=f"session {token_hash[:8]}",
        )
    target = "/admin/login" if token_hash == request.state.session_hash else "/admin/activity"
    return RedirectResponse(url=target, status_code=303)
