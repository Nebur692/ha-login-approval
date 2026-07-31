"""Bridge-page personalization: logo, background, favicon, title — so the
login screen doesn't look generic (requested explicitly by the user).
Uploads are decoded, resized, and re-encoded via app.image_utils before
being written to disk (see there for why — non-standard formats, oversized
photos), and only the resulting path is stored in the bridge_branding row,
keeping the SQLite file small and a trivial single-file backup.

Rendered on the actual login page by routers/idp.py (title, favicon, logo,
background), which also serves the files themselves at /branding/{kind}.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from app import image_utils
from app.branding import get_branding
from app.config import settings
from app.db import get_db
from app.routers.admin._auth import require_admin

from app.routers.admin._templates import templates

router = APIRouter()


async def _save_asset(upload: UploadFile | None, kind: str) -> str | None:
    if upload is None or not upload.filename:
        return None

    try:
        encoded, ext = image_utils.normalize(await upload.read(), kind)
    except image_utils.InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=f"{kind}: {exc}") from exc

    dest_dir = Path(settings.branding_asset_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{kind}.{ext}"
    dest.write_bytes(encoded)
    return str(dest)


@router.get("/admin/branding")
async def branding_page(request: Request, _: str = Depends(require_admin)):
    branding = await get_branding(get_db()) or {}
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

    existing = await get_branding(db)
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
