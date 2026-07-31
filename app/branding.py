"""Bridge-page branding: reads the single bridge_branding row. Shared by
the admin router (which writes it) and idp.py (which renders the title and
serves the asset files on the public login page).
"""
from pathlib import Path

CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg"}


async def get_branding(db) -> dict | None:
    cursor = await db.execute("SELECT * FROM bridge_branding WHERE id = 1")
    row = await cursor.fetchone()
    return dict(row) if row else None


def asset_path(branding: dict | None, kind: str) -> Path | None:
    path = (branding or {}).get(f"{kind}_path")
    return Path(path) if path else None
