import pytest

from app import db
from app.config import settings


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "test.db"))
    await db.init_db()
    yield db.get_db()
    await db.close_db()


async def test_migrations_apply_cleanly(temp_db):
    cursor = await temp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row["name"] for row in await cursor.fetchall()}
    assert {
        "schema_migrations",
        "recovery_code_generations",
        "recovery_codes",
        "login_events",
        "ip_block_state",
        "bridge_branding",
        "idp_signing_keys",
    }.issubset(tables)


async def test_migration_recorded_exactly_once(temp_db):
    cursor = await temp_db.execute("SELECT version FROM schema_migrations")
    versions = [row["version"] for row in await cursor.fetchall()]
    assert versions == [1]


async def test_init_db_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "test2.db"))
    await db.init_db()
    await db.init_db()  # second call must be a no-op, not re-apply/crash
    await db.close_db()


async def test_ip_block_state_scoped_to_account_and_ip(temp_db):
    """Composite primary key: same IP can be tracked independently per account."""
    await temp_db.execute(
        "INSERT INTO ip_block_state (account_id, ip, consecutive_failures) VALUES (?, ?, ?)",
        ("user-a", "203.0.113.5", 1),
    )
    await temp_db.execute(
        "INSERT INTO ip_block_state (account_id, ip, consecutive_failures) VALUES (?, ?, ?)",
        ("user-b", "203.0.113.5", 3),
    )
    await temp_db.commit()

    cursor = await temp_db.execute(
        "SELECT account_id, consecutive_failures FROM ip_block_state WHERE ip = ? ORDER BY account_id",
        ("203.0.113.5",),
    )
    rows = await cursor.fetchall()
    assert [(r["account_id"], r["consecutive_failures"]) for r in rows] == [
        ("user-a", 1),
        ("user-b", 3),
    ]
