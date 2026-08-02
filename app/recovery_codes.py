"""One-time recovery codes — the emergency valve for the passwordless flow
when the push notification can't be delivered/answered. Chosen over
"unassign devices from the admin panel" because that would leave the
account completely open with no check at all.

Codes are shown exactly once at generation time and stored only as
irreversible Argon2 hashes — never reversible encryption, since there's no
legitimate reason to show them again after generation.
"""
import asyncio
import secrets
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings

# OWASP's Argon2id profile (19 MiB, 2 passes, 1 lane) rather than the library
# default of 64 MiB and 4 lanes. Verifying a submitted code means hashing it
# once per unused code in the batch, so the default multiplied a deliberate
# ~80 ms into most of a second of work for a single request. Argon2 records its
# parameters inside each hash, so codes generated before this still verify.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

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



def _find_matching_code(candidates, code: str):
    """The one candidate whose hash matches, or None. Runs in a worker thread
    (see verify_code) — deliberately touches nothing but its arguments."""
    for candidate in candidates:
        try:
            _hasher.verify(candidate["code_hash"], code)
        except VerifyMismatchError:
            continue
        return candidate
    return None


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

    # Argon2 is meant to be slow, so running it here would stall every other
    # request on this worker — including unrelated logins waiting on their own
    # approval — for as long as the whole batch takes.
    matched = await asyncio.to_thread(_find_matching_code, candidates, code)
    if matched is not None:
        candidate = matched
        await db.execute(
            "UPDATE recovery_codes SET used_at = ?, used_ip = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), used_ip, candidate["id"]),
        )
        await db.commit()
        return True
    return False


async def has_ever_been_generated(db, account_id: str) -> bool:
    """Whether a batch was ever generated for this account. Distinct from
    `remaining_count() == 0`, which is also true for an account that never
    had any codes at all — the two cases need different wording in the
    warning notification, since "you've run out" is simply false for
    somebody who never generated a batch in the first place."""
    cursor = await db.execute(
        "SELECT 1 FROM recovery_code_generations WHERE account_id = ?",
        (account_id,),
    )
    return await cursor.fetchone() is not None


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
