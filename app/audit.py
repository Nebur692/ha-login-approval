"""Audit log for the passwordless flow: one row per login attempt outcome,
enriched with browser/IP (and, from Fase 4 on, city/country/ISP via GeoIP).
Feeds the admin panel's per-account history (Fase 7).
"""
from datetime import datetime, timezone

VALID_EVENT_TYPES = {"approved", "rejected", "timeout", "recovery_code_used", "send_failed", "blocked"}


async def log_event(db, account_id: str, request_id: str, event_type: str,
                     ip: str | None = None, user_agent: str | None = None,
                     geo_city: str | None = None, geo_country: str | None = None,
                     geo_asn_org: str | None = None) -> None:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"invalid event_type: {event_type!r}")

    await db.execute(
        "INSERT INTO login_events "
        "(account_id, request_id, event_type, occurred_at, ip, user_agent, "
        " geo_city, geo_country, geo_asn_org) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, request_id, event_type, datetime.now(timezone.utc).isoformat(),
         ip, user_agent, geo_city, geo_country, geo_asn_org),
    )
    await db.commit()


async def store_map(db, request_id: str, png: bytes) -> None:
    """The notification's map, kept for the audit log. One per login request:
    a second event for the same request (a resend, a recovery code after a
    timeout) keeps the first."""
    await db.execute(
        "INSERT OR IGNORE INTO login_maps (request_id, png, created_at) VALUES (?, ?, ?)",
        (request_id, png, datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()


async def get_map(db, request_id: str) -> bytes | None:
    cursor = await db.execute("SELECT png FROM login_maps WHERE request_id = ?", (request_id,))
    row = await cursor.fetchone()
    return row["png"] if row else None


async def list_events(db, account_id: str, limit: int = 50) -> list[dict]:
    cursor = await db.execute(
        "SELECT e.*, EXISTS (SELECT 1 FROM login_maps m WHERE m.request_id = e.request_id) AS has_map "
        "FROM login_events e WHERE e.account_id = ? ORDER BY e.occurred_at DESC LIMIT ?",
        (account_id, limit),
    )
    return [dict(row) for row in await cursor.fetchall()]
