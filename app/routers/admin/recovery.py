"""Generate/regenerate one-time recovery codes per account. Codes are
shown exactly once, right after generation — this page is the only place
they're ever visible in plaintext, and generating a new batch silently
invalidates every code from the previous one (recovery_codes.py)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates

from app import recovery_codes, zitadel_client
from app.db import get_db
from app.routers.admin._auth import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="templates")


async def _rows() -> list[dict]:
    users = await zitadel_client.list_users()
    human_users = [u for u in users if not u["is_machine"]]
    db = get_db()
    rows = []
    for u in human_users:
        remaining = await recovery_codes.remaining_count(db, u["id"])
        rows.append({**u, "remaining": remaining})
    return rows


@router.get("/admin/recovery")
async def recovery_page(request: Request, _: str = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/recovery.html", {
        "active": "recovery",
        "rows": await _rows(),
        "new_codes": None,
    })


@router.post("/admin/recovery/generate")
async def generate_codes(request: Request, user_id: str = Form(...), admin_user: str = Depends(require_admin)):
    codes = await recovery_codes.generate_batch(get_db(), user_id, generated_by=admin_user)
    rows = await _rows()
    generated_for = next((r["display_name"] for r in rows if r["id"] == user_id), user_id)

    return templates.TemplateResponse(request, "admin/recovery.html", {
        "active": "recovery",
        "rows": rows,
        "new_codes": codes,
        "new_codes_for": generated_for,
    })
