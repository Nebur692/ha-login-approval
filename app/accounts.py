"""The account directory for the passwordless OIDC flow (routers/idp.py) —
email -> assigned HA notify targets, stored entirely in our own SQLite.
Deliberately independent of any relying party's admin API (ZITADEL,
Keycloak, Authentik, ...): this project's whole point is to work as an
external IDP for any of them, so it never talks to a specific RP to figure
out who's who.
"""
import json
from datetime import datetime, timezone


def _normalize(email: str) -> str:
    return email.strip().lower()


async def get_targets(db, email: str) -> list[str]:
    cursor = await db.execute(
        "SELECT ha_notify_targets FROM accounts WHERE email = ?", (_normalize(email),)
    )
    row = await cursor.fetchone()
    return json.loads(row["ha_notify_targets"]) if row else []


async def set_targets(db, email: str, targets: list[str]) -> None:
    email = _normalize(email)
    now = datetime.now(timezone.utc).isoformat()

    cursor = await db.execute("SELECT 1 FROM accounts WHERE email = ?", (email,))
    if await cursor.fetchone():
        await db.execute(
            "UPDATE accounts SET ha_notify_targets = ?, updated_at = ? WHERE email = ?",
            (json.dumps(targets), now, email),
        )
    else:
        await db.execute(
            "INSERT INTO accounts (email, ha_notify_targets, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (email, json.dumps(targets), now, now),
        )
    await db.commit()


async def account_exists(db, email: str) -> bool:
    cursor = await db.execute("SELECT 1 FROM accounts WHERE email = ?", (_normalize(email),))
    return await cursor.fetchone() is not None


async def list_accounts(db) -> list[dict]:
    cursor = await db.execute(
        "SELECT email, ha_notify_targets FROM accounts ORDER BY email"
    )
    return [
        {"email": row["email"], "targets": json.loads(row["ha_notify_targets"])}
        for row in await cursor.fetchall()
    ]
