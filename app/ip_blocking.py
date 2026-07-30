"""IP-block counter — 3 consecutive failures (explicit rejects + wrong
recovery codes, counted on the same counter) block the same (account, IP)
pair. Deliberately scoped to account+IP, never a global IP block: the
composite primary key on ip_block_state makes it structurally impossible
for an attacker to lock out the real account owner's own IP unless they're
actually attacking from it.

Not a time-window rate limit — consecutive failures only, reset by any
success (a real approval or a correct recovery code).
"""
from datetime import datetime, timezone

from app.config import settings


async def _get_state(db, zitadel_user_id: str, ip: str):
    cursor = await db.execute(
        "SELECT * FROM ip_block_state WHERE zitadel_user_id = ? AND ip = ?",
        (zitadel_user_id, ip),
    )
    return await cursor.fetchone()


async def is_blocked(db, zitadel_user_id: str, ip: str) -> bool:
    row = await _get_state(db, zitadel_user_id, ip)
    return row is not None and row["blocked_at"] is not None and row["unblocked_at"] is None


async def record_failure(db, zitadel_user_id: str, ip: str) -> bool:
    """Increments the consecutive-failure counter for (account, ip).
    Returns True if this failure just crossed the block threshold."""
    row = await _get_state(db, zitadel_user_id, ip)
    now = datetime.now(timezone.utc).isoformat()

    if row is None:
        failures = 1
        await db.execute(
            "INSERT INTO ip_block_state (zitadel_user_id, ip, consecutive_failures) VALUES (?, ?, ?)",
            (zitadel_user_id, ip, failures),
        )
    else:
        failures = row["consecutive_failures"] + 1
        await db.execute(
            "UPDATE ip_block_state SET consecutive_failures = ? WHERE zitadel_user_id = ? AND ip = ?",
            (failures, zitadel_user_id, ip),
        )

    just_blocked = failures >= settings.ip_block_threshold and (row is None or row["blocked_at"] is None)
    if just_blocked:
        await db.execute(
            "UPDATE ip_block_state SET blocked_at = ?, unblocked_at = NULL, unblocked_by = NULL "
            "WHERE zitadel_user_id = ? AND ip = ?",
            (now, zitadel_user_id, ip),
        )

    await db.commit()
    return just_blocked


async def record_success(db, zitadel_user_id: str, ip: str) -> None:
    """Any successful approval or correct recovery code resets the counter
    — a real login shouldn't be shadowed by earlier unrelated failures."""
    await db.execute(
        "UPDATE ip_block_state SET consecutive_failures = 0, blocked_at = NULL, "
        "unblocked_at = NULL, unblocked_by = NULL WHERE zitadel_user_id = ? AND ip = ?",
        (zitadel_user_id, ip),
    )
    await db.commit()


async def unblock(db, zitadel_user_id: str, ip: str, unblocked_by: str) -> None:
    """Manual unblock from the admin panel — e.g. after an accidental
    triple-reject locks out the real account owner."""
    await db.execute(
        "UPDATE ip_block_state SET consecutive_failures = 0, unblocked_at = ?, unblocked_by = ? "
        "WHERE zitadel_user_id = ? AND ip = ?",
        (datetime.now(timezone.utc).isoformat(), unblocked_by, zitadel_user_id, ip),
    )
    await db.commit()


async def list_blocked(db) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM ip_block_state WHERE blocked_at IS NOT NULL AND unblocked_at IS NULL "
        "ORDER BY blocked_at DESC"
    )
    return [dict(row) for row in await cursor.fetchall()]
