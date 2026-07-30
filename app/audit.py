"""Audit log for the passwordless flow: one row per login attempt outcome,
enriched with browser/IP (and, from Fase 4 on, city/country/ISP via GeoIP).
Feeds the admin panel's per-account history (Fase 7).
"""
from datetime import datetime, timezone

VALID_EVENT_TYPES = {"approved", "rejected", "timeout", "recovery_code_used", "send_failed", "blocked"}


async def log_event(db, zitadel_user_id: str, request_id: str, event_type: str,
                     ip: str | None = None, user_agent: str | None = None,
                     geo_city: str | None = None, geo_country: str | None = None,
                     geo_asn_org: str | None = None) -> None:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"invalid event_type: {event_type!r}")

    await db.execute(
        "INSERT INTO login_events "
        "(zitadel_user_id, request_id, event_type, occurred_at, ip, user_agent, "
        " geo_city, geo_country, geo_asn_org) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (zitadel_user_id, request_id, event_type, datetime.now(timezone.utc).isoformat(),
         ip, user_agent, geo_city, geo_country, geo_asn_org),
    )
    await db.commit()


async def list_events(db, zitadel_user_id: str, limit: int = 50) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM login_events WHERE zitadel_user_id = ? ORDER BY occurred_at DESC LIMIT ?",
        (zitadel_user_id, limit),
    )
    return [dict(row) for row in await cursor.fetchall()]
