"""Bridge-page personalization: logo, background, favicon, title — so the
login screen doesn't look generic (requested explicitly by the user).
Binaries are stored as files on disk under branding_asset_dir; only the
path is stored in the bridge_branding row, keeping the SQLite file small
and a trivial single-file backup.

Not yet wired into templates/idp_bridge.html's actual rendering — that's
left for the polish pass in Fase 9, once the whole v2.0.0 feature set is
otherwise complete.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import get_db
from app.routers.admin._auth import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="templates")


async def _get_branding(db) -> dict | None:
    cursor = await db.execute("SELECT * FROM bridge_branding WHERE id = 1")
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _save_asset(upload: UploadFile | None, filename: str) -> str | None:
    if upload is None or not upload.filename:
        return None
    dest_dir = Path(settings.branding_asset_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(await upload.read())
    return str(dest)


@router.get("/admin/branding")
async def branding_page(request: Request, _: str = Depends(require_admin)):
    branding = await _get_branding(get_db()) or {}
    return templates.TemplateResponse(request, "admin/branding.html", {
        "active": "branding",
        "branding": branding,
    })


@router.post("/admin/branding/save")
async def save_branding(
    title: str = Form(""),
    logo: UploadFile | None = None,
    background: UploadFile | None = None,
    favicon: UploadFile | None = None,
    _: str = Depends(require_admin),
):
    db = get_db()
    logo_path = await _save_asset(logo, "logo")
    background_path = await _save_asset(background, "background")
    favicon_path = await _save_asset(favicon, "favicon")
    now = datetime.now(timezone.utc).isoformat()

    existing = await _get_branding(db)
    if existing:
        await db.execute(
            "UPDATE bridge_branding SET title = ?, "
            "logo_path = COALESCE(?, logo_path), "
            "background_path = COALESCE(?, background_path), "
            "favicon_path = COALESCE(?, favicon_path), "
            "updated_at = ? WHERE id = 1",
            (title, logo_path, background_path, favicon_path, now),
        )
    else:
        await db.execute(
            "INSERT INTO bridge_branding (id, title, logo_path, background_path, favicon_path, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (title, logo_path, background_path, favicon_path, now),
        )
    await db.commit()
    return RedirectResponse(url="/admin/branding", status_code=303)
