"""Rotate the key that signs id_tokens. Shows only kids and dates — the
private key never leaves the database (idp_jwt.py)."""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import admin_sessions, client_ip, idp_jwt
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/signing-key")
async def signing_key_page(request: Request, _: str = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/signing_key.html", {
        "active": "signing_key",
        "keys": await idp_jwt.list_keys(),
        "overlap_minutes": int(idp_jwt.ROTATION_OVERLAP.total_seconds() // 60),
    })


@router.post("/admin/signing-key/rotate")
async def rotate(request: Request, discard_old: str | None = Form(None), admin_user: str = Depends(require_admin)):
    kid = await idp_jwt.rotate_signing_key(discard_old=discard_old == "yes")
    await admin_sessions.record(
        "signing_key_rotated", username=admin_user, ip=client_ip.resolve(request),
        detail=f"new {kid[:8]}, old {'deleted' if discard_old == 'yes' else 'kept for the overlap'}",
    )
    logger.warning(
        "Signing key rotated by %s — new kid %s, old key %s",
        admin_user, kid, "discarded" if discard_old == "yes" else "kept for the overlap",
    )
    return RedirectResponse(url="/admin/signing-key", status_code=303)
