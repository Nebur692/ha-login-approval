import os
import sqlite3
import stat
from datetime import timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from jwt import PyJWK

from app import db, idp_jwt
from app.config import settings
AUTH = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}  # admin:test-admin-password

MIGRATION_0001 = Path(__file__).resolve().parent.parent / "app" / "migrations" / "0001_init.sql"


@pytest.fixture
async def keys_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "keys.db"))
    await db.init_db()
    await idp_jwt.ensure_signing_key()
    yield
    await db.close_db()


def _token() -> str:
    return idp_jwt.build_id_token(issuer="http://i", audience="rp", subject="s", email="s@example.com")


def _verifies_with_jwks(token: str) -> bool:
    kid = pyjwt.get_unverified_header(token)["kid"]
    for jwk in idp_jwt.get_jwks()["keys"]:
        if jwk["kid"] == kid:
            pyjwt.decode(token, key=PyJWK.from_dict(jwk).key, algorithms=["RS256"], audience="rp")
            return True
    return False


async def test_rotation_keeps_the_old_key_verifying_during_the_overlap(keys_ready):
    old_token = _token()
    old_kid = pyjwt.get_unverified_header(old_token)["kid"]
    new_kid = await idp_jwt.rotate_signing_key()

    assert new_kid != old_kid
    assert pyjwt.get_unverified_header(_token())["kid"] == new_kid
    assert {k["kid"] for k in idp_jwt.get_jwks()["keys"]} == {old_kid, new_kid}
    assert _verifies_with_jwks(old_token)
    assert _verifies_with_jwks(_token())


async def test_discarding_removes_the_old_key_at_once(keys_ready):
    old_token = _token()
    await idp_jwt.rotate_signing_key(discard_old=True)
    assert len(idp_jwt.get_jwks()["keys"]) == 1
    assert not _verifies_with_jwks(old_token)
    assert len(await idp_jwt.list_keys()) == 1


async def test_retired_key_leaves_the_jwks_and_the_database_after_the_overlap(keys_ready, monkeypatch):
    await idp_jwt.rotate_signing_key()
    await idp_jwt.rotate_signing_key()  # several rotations: two retired keys
    assert len(idp_jwt.get_jwks()["keys"]) == 3

    monkeypatch.setattr(idp_jwt, "ROTATION_OVERLAP", timedelta(seconds=-1))
    # off the JWKS straight away, even before any purge runs ...
    assert len(idp_jwt.get_jwks()["keys"]) == 1
    # ... and the private keys are gone once it does
    await idp_jwt.purge_retired_keys()
    rows = await idp_jwt.list_keys()
    assert [r["active"] for r in rows] == [1]


async def test_key_survives_a_restart(keys_ready):
    kid = await idp_jwt.rotate_signing_key()
    await idp_jwt.ensure_signing_key()
    assert pyjwt.get_unverified_header(_token())["kid"] == kid


async def test_admin_list_never_carries_the_private_key(keys_ready):
    for row in await idp_jwt.list_keys():
        assert set(row) == {"kid", "created_at", "active", "retired_at"}


async def test_database_file_is_owner_only(keys_ready):
    mode = stat.S_IMODE(os.stat(settings.sqlite_db_path).st_mode)
    assert mode == 0o600


async def test_upgrade_from_a_v2_4_database_keeps_its_key(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(MIGRATION_0001.read_text())
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    con.execute("INSERT INTO schema_migrations VALUES (1, datetime('now'))")
    con.commit()
    con.close()
    os.chmod(path, 0o644)
    monkeypatch.setattr(settings, "sqlite_db_path", str(path))

    await db.init_db()
    await idp_jwt.ensure_signing_key()
    first_kid = (await idp_jwt.list_keys())[0]["kid"]
    await db.close_db()

    # what an existing install looks like: a key made by the old code, no retired_at
    await db.init_db()
    await idp_jwt.ensure_signing_key()
    rows = await idp_jwt.list_keys()
    assert [(r["kid"], r["active"], r["retired_at"]) for r in rows] == [(first_kid, 1, None)]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    await db.close_db()


async def test_rotate_from_the_admin_panel(client, keys_ready):
    before = (await idp_jwt.list_keys())[0]["kid"]
    resp = await client.post("/admin/signing-key/rotate", headers=AUTH, follow_redirects=False)
    assert resp.status_code == 303
    rows = await idp_jwt.list_keys()
    assert [r["kid"] for r in rows if not r["active"]] == [before]

    resp = await client.post("/admin/signing-key/rotate", headers=AUTH, data={"discard_old": "yes"}, follow_redirects=False)
    assert resp.status_code == 303
    rows = await idp_jwt.list_keys()
    assert len([r for r in rows if r["active"]]) == 1
    assert before in [r["kid"] for r in rows]  # the earlier retired one is untouched by a discard

    page = await client.get("/admin/signing-key", headers=AUTH)
    assert page.status_code == 200
    assert rows[0]["kid"] in page.text
    assert "PRIVATE KEY" not in page.text
