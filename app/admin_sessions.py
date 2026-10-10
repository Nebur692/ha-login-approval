"""Admin panel sign-in: sessions, the attempt limit, and the record of what is
done in the panel.

Replaces HTTP Basic Auth, which sent the password with every request, could
not be signed out of, let any page on the internet submit a form into the
panel with the browser's cached credentials, and had no limit on guesses —
for a panel reachable from the internet.

- A session is a random token in an HttpOnly, SameSite=Strict cookie. Only its
  SHA-256 is stored, so a copy of the database is not a way in. It ends after
  IDLE_TIMEOUT without use, or ABSOLUTE_TIMEOUT after sign-in, whichever
  comes first.
- Every form that changes something carries the session's CSRF token.
- Failed sign-ins are counted per address and overall; past the limit the
  panel refuses even the right password until the window has passed.
- A password that is short or well known disables the panel instead of
  protecting it badly. The sign-in flow itself is never affected.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import get_db

IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=8)

FAILURE_WINDOW = timedelta(minutes=15)
FAILURES_PER_ADDRESS = 5
FAILURES_OVERALL = 50
"""Overall, across every address: someone with many addresses gets the same
handful of guesses, not a handful each."""

MIN_PASSWORD_LENGTH = 12
_WELL_KNOWN = {
    "admin", "administrator", "changeme", "change_me", "password", "passw0rd", "letmein",
    "123456", "12345678", "123456789", "1234567890", "qwerty", "secret", "homeassistant",
}

_MAX_USER_AGENT = 256

LOGIN_OK = "login_ok"
LOGIN_FAILED = "login_failed"
LOGIN_REFUSED = "login_refused"
"""Right or wrong, refused because the attempt limit was reached."""
LOGOUT = "logout"
SESSION_ENDED = "session_ended"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_problem() -> str | None:
    """Why the configured admin password is not good enough, or None."""
    password = settings.admin_password
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"ADMIN_PASSWORD is shorter than {MIN_PASSWORD_LENGTH} characters."
    if password.lower() in _WELL_KNOWN or password.lower() == settings.admin_username.lower():
        return "ADMIN_PASSWORD is a default or well-known password."
    return None


def credentials_match(username: str, password: str) -> bool:
    # Both compared every time, as bytes: no early exit that would time the
    # username apart from the password, and no TypeError on a non-ASCII
    # character (compare_digest refuses non-ASCII str).
    user_ok = secrets.compare_digest(username.encode("utf-8"), settings.admin_username.encode("utf-8"))
    pass_ok = secrets.compare_digest(password.encode("utf-8"), settings.admin_password.encode("utf-8"))
    return user_ok and pass_ok


async def record(event: str, *, username: str = "", ip: str = "", detail: str = "") -> None:
    db = get_db()
    await db.execute(
        "INSERT INTO admin_events (at, username, ip, event, detail) VALUES (?, ?, ?, ?, ?)",
        (_now().isoformat(), username[:128], ip[:64], event, detail[:500]),
    )
    await db.commit()


async def too_many_failures(ip: str) -> bool:
    since = (_now() - FAILURE_WINDOW).isoformat()
    db = get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM admin_events WHERE event = ? AND ip = ? AND at > ?", (LOGIN_FAILED, ip, since),
    )
    if (await cursor.fetchone())[0] >= FAILURES_PER_ADDRESS:
        return True
    cursor = await db.execute("SELECT COUNT(*) FROM admin_events WHERE event = ? AND at > ?", (LOGIN_FAILED, since))
    return (await cursor.fetchone())[0] >= FAILURES_OVERALL


async def create(username: str, ip: str, user_agent: str) -> str:
    """Starts a session and returns its token — the only time it exists in
    the clear, on its way into the cookie."""
    token = secrets.token_urlsafe(32)
    now = _now().isoformat()
    db = get_db()
    await _purge_expired(db)
    await db.execute(
        "INSERT INTO admin_sessions (token_hash, username, csrf_token, created_at, last_seen_at, ip, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_hash(token), username, secrets.token_urlsafe(32), now, now, ip, user_agent[:_MAX_USER_AGENT]),
    )
    await db.commit()
    return token


async def lookup(token: str | None) -> dict | None:
    """The live session for this token, its last use moved to now; or None."""
    if not token:
        return None
    db = get_db()
    cursor = await db.execute("SELECT * FROM admin_sessions WHERE token_hash = ?", (_hash(token),))
    row = await cursor.fetchone()
    if row is None:
        return None
    now = _now()
    if (now - datetime.fromisoformat(row["last_seen_at"]) > IDLE_TIMEOUT
            or now - datetime.fromisoformat(row["created_at"]) > ABSOLUTE_TIMEOUT):
        await db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (row["token_hash"],))
        await db.commit()
        return None
    await db.execute(
        "UPDATE admin_sessions SET last_seen_at = ? WHERE token_hash = ?", (now.isoformat(), row["token_hash"]),
    )
    await db.commit()
    return dict(row)


async def end(token_hash: str) -> bool:
    db = get_db()
    cursor = await db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
    await db.commit()
    return cursor.rowcount > 0


def hash_of(token: str) -> str:
    return _hash(token)


async def list_sessions() -> list[dict]:
    db = get_db()
    await _purge_expired(db)
    await db.commit()
    cursor = await db.execute(
        "SELECT token_hash, username, created_at, last_seen_at, ip, user_agent FROM admin_sessions "
        "ORDER BY last_seen_at DESC"
    )
    return [dict(row) for row in await cursor.fetchall()]


async def list_events(limit: int = 200) -> list[dict]:
    cursor = await get_db().execute(
        "SELECT at, username, ip, event, detail FROM admin_events ORDER BY id DESC LIMIT ?", (limit,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def _purge_expired(db) -> None:
    now = _now()
    await db.execute(
        "DELETE FROM admin_sessions WHERE last_seen_at < ? OR created_at < ?",
        ((now - IDLE_TIMEOUT).isoformat(), (now - ABSOLUTE_TIMEOUT).isoformat()),
    )
