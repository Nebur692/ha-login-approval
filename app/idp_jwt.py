"""Signing key management + id_token issuance for the passwordless OIDC
provider. The RSA keypair is generated once and persisted in SQLite
(idp_signing_keys) so it survives container restarts.

Rotation (v2.3.0), from the admin panel: a new key starts signing at once.
The old one, by default, stays published in the JWKS for an overlap window,
so a token it signed moments before still verifies at the relying party; a
relying party meeting the new `kid` refetches the JWKS on its own. If the
old key may have leaked, it can be discarded on the spot instead — any login
in flight at that second fails and has to be retried, which is the point.
"""
import base64
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.db import get_db

ALGORITHM = "RS256"

# id_tokens live 5 minutes and are redeemed within seconds; an hour is ample
# for anything signed just before a rotation, and short enough that a retired
# private key does not linger.
ROTATION_OVERLAP = timedelta(hours=1)

_active_kid: str | None = None
_private_key_pem: str | None = None
_published: list[dict] = []
"""Keys in the JWKS: the active one, plus retired ones still in overlap —
each {kid, public_numbers, retired_at (datetime | None)}."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


async def _insert_active_key(db) -> None:
    private_pem, public_pem = _new_keypair()
    await db.execute(
        "INSERT INTO idp_signing_keys (kid, private_key_pem, public_key_pem, created_at, active) "
        "VALUES (?, ?, ?, ?, 1)",
        (uuid.uuid4().hex, private_pem, public_pem, _now().isoformat()),
    )


async def _purge_expired(db) -> None:
    cutoff = (_now() - ROTATION_OVERLAP).isoformat()
    await db.execute(
        "DELETE FROM idp_signing_keys WHERE active = 0 AND (retired_at IS NULL OR retired_at <= ?)",
        (cutoff,),
    )


async def _load(db) -> None:
    global _active_kid, _private_key_pem, _published
    cursor = await db.execute(
        "SELECT kid, private_key_pem, public_key_pem, active, retired_at FROM idp_signing_keys "
        "ORDER BY active DESC, created_at DESC"
    )
    published = []
    for row in await cursor.fetchall():
        if row["active"]:
            _active_kid = row["kid"]
            _private_key_pem = row["private_key_pem"]
        public_key = serialization.load_pem_public_key(row["public_key_pem"].encode())
        published.append({
            "kid": row["kid"],
            "public_numbers": public_key.public_numbers(),
            "retired_at": datetime.fromisoformat(row["retired_at"]) if row["retired_at"] else None,
        })
    _published = published


async def ensure_signing_key() -> None:
    """Loads the active signing key from the DB, generating and persisting
    a new one on first run. Call once at startup, after db.init_db()."""
    db = get_db()
    await _purge_expired(db)
    cursor = await db.execute("SELECT 1 FROM idp_signing_keys WHERE active = 1 LIMIT 1")
    if await cursor.fetchone() is None:
        await _insert_active_key(db)
    await db.commit()
    await _load(db)


async def rotate_signing_key(discard_old: bool = False) -> str:
    """Makes a fresh key the signing key and returns its kid. The old one
    keeps verifying for ROTATION_OVERLAP, or is deleted now with discard_old."""
    db = get_db()
    if discard_old:
        await db.execute("DELETE FROM idp_signing_keys WHERE active = 1")
    else:
        await db.execute(
            "UPDATE idp_signing_keys SET active = 0, retired_at = ? WHERE active = 1",
            (_now().isoformat(),),
        )
    await _insert_active_key(db)
    await _purge_expired(db)
    await db.commit()
    await _load(db)
    return _active_kid


async def purge_retired_keys() -> None:
    """Deletes retired keys whose overlap is over — run periodically, so a
    retired private key is gone within minutes of no longer being needed."""
    db = get_db()
    await _purge_expired(db)
    await db.commit()
    await _load(db)


async def list_keys() -> list[dict]:
    """For the admin panel: kid, created_at, active, retired_at — never the key."""
    cursor = await get_db().execute(
        "SELECT kid, created_at, active, retired_at FROM idp_signing_keys ORDER BY active DESC, created_at DESC"
    )
    return [dict(row) for row in await cursor.fetchall()]


def _require_key() -> None:
    if _private_key_pem is None:
        raise RuntimeError("Signing key not loaded — call ensure_signing_key() first")


def build_id_token(
    issuer: str, audience: str, subject: str, email: str, ttl_seconds: int = 300, nonce: str | None = None,
) -> str:
    _require_key()
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": now,
        "exp": now + ttl_seconds,
        "email": email,
        "email_verified": True,
        "preferred_username": email,
    }
    # OIDC Core §3.1.3.6: a nonce sent to /authorize must come back unchanged,
    # and a client that sent one rejects a token without it.
    if nonce is not None:
        claims["nonce"] = nonce
    return jwt.encode(claims, _private_key_pem, algorithm=ALGORITHM, headers={"kid": _active_kid})


def get_jwks() -> dict:
    _require_key()

    def b64u(n: int) -> str:
        length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    # Filtered here too, not only by the periodic purge: an expired key must
    # leave the JWKS on time even if the purge has not run yet.
    cutoff = _now() - ROTATION_OVERLAP
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": ALGORITHM,
                "kid": key["kid"],
                "n": b64u(key["public_numbers"].n),
                "e": b64u(key["public_numbers"].e),
            }
            for key in _published
            if key["retired_at"] is None or key["retired_at"] > cutoff
        ]
    }
