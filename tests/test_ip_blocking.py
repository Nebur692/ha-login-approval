import pytest

from app import db, ip_blocking
from app.config import settings

IP = "203.0.113.5"


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "ipblock.db"))
    monkeypatch.setattr(settings, "ip_block_threshold", 3)
    await db.init_db()
    yield db.get_db()
    await db.close_db()


async def test_not_blocked_initially(temp_db):
    assert await ip_blocking.is_blocked(temp_db, "user-a", IP) is False


async def test_blocks_after_threshold_consecutive_failures(temp_db):
    assert await ip_blocking.record_failure(temp_db, "user-a", IP) is False
    assert await ip_blocking.record_failure(temp_db, "user-a", IP) is False
    assert await ip_blocking.record_failure(temp_db, "user-a", IP) is True  # crosses threshold=3

    assert await ip_blocking.is_blocked(temp_db, "user-a", IP) is True


async def test_success_resets_counter(temp_db):
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_success(temp_db, "user-a", IP)

    # Two prior failures shouldn't carry over after a success.
    assert await ip_blocking.record_failure(temp_db, "user-a", IP) is False
    assert await ip_blocking.is_blocked(temp_db, "user-a", IP) is False


async def test_scoped_to_account_and_ip_independently(temp_db):
    """Same IP, two different accounts — failures on one must not affect the other."""
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    assert await ip_blocking.is_blocked(temp_db, "user-a", IP) is True
    assert await ip_blocking.is_blocked(temp_db, "user-b", IP) is False


async def test_manual_unblock_clears_state(temp_db):
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    assert await ip_blocking.is_blocked(temp_db, "user-a", IP) is True

    await ip_blocking.unblock(temp_db, "user-a", IP, unblocked_by="admin")
    assert await ip_blocking.is_blocked(temp_db, "user-a", IP) is False
    # Unblocking also resets the counter, not just the blocked flag.
    assert await ip_blocking.record_failure(temp_db, "user-a", IP) is False


async def test_list_blocked_only_shows_currently_blocked(temp_db):
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-a", IP)
    await ip_blocking.record_failure(temp_db, "user-b", "198.51.100.9")  # below threshold

    blocked = await ip_blocking.list_blocked(temp_db)
    assert len(blocked) == 1
    assert blocked[0]["account_id"] == "user-a"

    await ip_blocking.unblock(temp_db, "user-a", IP, unblocked_by="admin")
    assert await ip_blocking.list_blocked(temp_db) == []
