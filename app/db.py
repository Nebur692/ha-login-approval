"""SQLite connection + migration runner.

Introduced in v2.0.0 for state ZITADEL's per-user metadata API is a poor fit
for: recovery codes, audit log, IP-block counters, bridge-page branding.
`ha_notify_targets` (device assignment) stays in ZITADEL metadata — see
zitadel_client.py — a single small value per user, already a good fit there.

Migrations are plain additive .sql scripts under app/migrations/, named
`NNNN_description.sql`, applied in order and tracked in schema_migrations —
never edit a migration after it's shipped, add a new one instead.
"""
import logging
from pathlib import Path

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    global _db
    if _db is not None:
        return
    db = await aiosqlite.connect(settings.sqlite_db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await _run_migrations(db)
    _db = db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    return _db


async def _run_migrations(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    await db.commit()

    cursor = await db.execute("SELECT version FROM schema_migrations")
    applied = {row["version"] for row in await cursor.fetchall()}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(path.stem.split("_")[0])
        if version in applied:
            continue
        logger.info("Applying migration %s", path.name)
        await db.executescript(path.read_text())
        await db.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        await db.commit()
