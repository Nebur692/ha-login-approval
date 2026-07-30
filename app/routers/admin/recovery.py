"""Generate/regenerate one-time recovery codes per passwordless account
(accounts.py). Codes are shown exactly once, right after generation —
this page is the only place they're ever visible in plaintext, and
generating a new batch silently invalidates every code from the previous
one (recovery_codes.py)."""
from fastapi import APIRouter, Depends, Form, Request

from app import accounts, recovery_codes
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


async def _rows() -> list[dict]:
    db = get_db()
    rows = []
    for a in await accounts.list_accounts(db):
        remaining = await recovery_codes.remaining_count(db, a["email"])
        rows.append({"email": a["email"], "remaining": remaining})
    return rows


@router.get("/admin/recovery")
async def recovery_page(request: Request, _: str = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/recovery.html", {
        "active": "recovery",
        "rows": await _rows(),
        "new_codes": None,
    })


@router.post("/admin/recovery/generate")
async def generate_codes(request: Request, email: str = Form(...), admin_user: str = Depends(require_admin)):
    account_id = email.strip().lower()
    codes = await recovery_codes.generate_batch(get_db(), account_id, generated_by=admin_user)

    return templates.TemplateResponse(request, "admin/recovery.html", {
        "active": "recovery",
        "rows": await _rows(),
        "new_codes": codes,
        "new_codes_for": account_id,
    })
