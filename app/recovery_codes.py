"""One-time recovery codes — the emergency valve for the passwordless flow
when the push notification can't be delivered/answered. Chosen over
"unassign devices from the admin panel" because that would leave the
account completely open with no check at all.

Codes are shown exactly once at generation time and stored only as
irreversible Argon2 hashes — never reversible encryption, since there's no
legitimate reason to show them again after generation.
"""
import secrets
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()

# Avoids visually ambiguous characters (0/O, 1/I/L).
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _generate_code() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


async def generate_batch(db, account_id: str, generated_by: str,
                          count: int | None = None) -> list[str]:
    """Generates a new batch of codes, invalidating every code from any
    previous generation for this account. Returns the plaintext codes —
    this is the only time they're ever available in that form."""
    count = count or settings.recovery_code_batch_size
    now = datetime.now(timezone.utc).isoformat()

    cursor = await db.execute(
        "SELECT current_generation FROM recovery_code_generations WHERE account_id = ?",
        (account_id,),
    )
    row = await cursor.fetchone()
    new_generation = (row["current_generation"] + 1) if row else 1

    if row:
        await db.execute(
            "UPDATE recovery_code_generations SET current_generation = ?, generated_at = ?, "
            "generated_by = ?, code_count = ? WHERE account_id = ?",
            (new_generation, now, generated_by, count, account_id),
        )
    else:
        await db.execute(
            "INSERT INTO recovery_code_generations "
            "(account_id, current_generation, generated_at, generated_by, code_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_id, new_generation, now, generated_by, count),
        )

    codes = []
    for _ in range(count):
        code = _generate_code()
        codes.append(code)
        await db.execute(
            "INSERT INTO recovery_codes (account_id, code_hash, generation, created_at) "
            "VALUES (?, ?, ?, ?)",
            (account_id, _hasher.hash(code), new_generation, now),
        )
    await db.commit()
    return codes


async def verify_code(db, account_id: str, code: str, used_ip: str) -> bool:
    """Checks `code` against this account's current generation of unused
    codes. On success, marks that specific code used (never reusable
    again) and returns True."""
    cursor = await db.execute(
        "SELECT current_generation FROM recovery_code_generations WHERE account_id = ?",
        (account_id,),
    )
    gen_row = await cursor.fetchone()
    if gen_row is None:
        return False

    cursor = await db.execute(
        "SELECT id, code_hash FROM recovery_codes "
        "WHERE account_id = ? AND generation = ? AND used_at IS NULL",
        (account_id, gen_row["current_generation"]),
    )
    candidates = await cursor.fetchall()

    for candidate in candidates:
        try:
            _hasher.verify(candidate["code_hash"], code)
        except VerifyMismatchError:
            continue
        await db.execute(
            "UPDATE recovery_codes SET used_at = ?, used_ip = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), used_ip, candidate["id"]),
        )
        await db.commit()
        return True
    return False


async def remaining_count(db, account_id: str) -> int:
    cursor = await db.execute(
        "SELECT current_generation FROM recovery_code_generations WHERE account_id = ?",
        (account_id,),
    )
    gen_row = await cursor.fetchone()
    if gen_row is None:
        return 0

    cursor = await db.execute(
        "SELECT COUNT(*) AS n FROM recovery_codes "
        "WHERE account_id = ? AND generation = ? AND used_at IS NULL",
        (account_id, gen_row["current_generation"]),
    )
    return (await cursor.fetchone())["n"]
