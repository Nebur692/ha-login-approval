"""Signing key management + id_token issuance for the passwordless OIDC
provider (v2.0.0). The RSA keypair is generated once and persisted in
SQLite (idp_signing_keys) so it survives container restarts — rotating it
unexpectedly would break every RP's cached JWKS.
"""
import base64
import time
import uuid
from datetime import datetime, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.db import get_db

ALGORITHM = "RS256"

_active_kid: str | None = None
_private_key_pem: str | None = None
_public_numbers = None


async def ensure_signing_key() -> None:
    """Loads the active signing key from the DB, generating and persisting
    a new one on first run. Call once at startup, after db.init_db()."""
    global _active_kid, _private_key_pem, _public_numbers

    db = get_db()
    cursor = await db.execute(
        "SELECT kid, private_key_pem, public_key_pem FROM idp_signing_keys WHERE active = 1 LIMIT 1"
    )
    row = await cursor.fetchone()

    if row is None:
        kid = uuid.uuid4().hex
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
        await db.execute(
            "INSERT INTO idp_signing_keys (kid, private_key_pem, public_key_pem, created_at, active) "
            "VALUES (?, ?, ?, ?, 1)",
            (kid, private_pem, public_pem, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
        row = {"kid": kid, "private_key_pem": private_pem, "public_key_pem": public_pem}

    _active_kid = row["kid"]
    _private_key_pem = row["private_key_pem"]
    public_key = serialization.load_pem_public_key(row["public_key_pem"].encode())
    _public_numbers = public_key.public_numbers()


def _require_key() -> None:
    if _private_key_pem is None:
        raise RuntimeError("Signing key not loaded — call ensure_signing_key() first")


def build_id_token(issuer: str, audience: str, subject: str, email: str, ttl_seconds: int = 300) -> str:
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
    }
    return jwt.encode(claims, _private_key_pem, algorithm=ALGORITHM, headers={"kid": _active_kid})


def get_jwks() -> dict:
    _require_key()

    def b64u(n: int) -> str:
        length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    return {
        "keys": [{
            "kty": "RSA",
            "use": "sig",
            "alg": ALGORITHM,
            "kid": _active_kid,
            "n": b64u(_public_numbers.n),
            "e": b64u(_public_numbers.e),
        }]
    }
