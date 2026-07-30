import pytest

from app import audit, db
from app.config import settings


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "audit.db"))
    await db.init_db()
    yield db.get_db()
    await db.close_db()


async def test_log_event_and_list(temp_db):
    await audit.log_event(temp_db, "user-1", "req-1", "approved", ip="1.2.3.4", user_agent="Chrome")
    events = await audit.list_events(temp_db, "user-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "approved"
    assert events[0]["ip"] == "1.2.3.4"


async def test_rejects_invalid_event_type(temp_db):
    with pytest.raises(ValueError):
        await audit.log_event(temp_db, "user-1", "req-1", "not_a_real_type")


async def test_list_events_ordered_most_recent_first(temp_db):
    await audit.log_event(temp_db, "user-1", "req-1", "timeout")
    await audit.log_event(temp_db, "user-1", "req-2", "approved")
    events = await audit.list_events(temp_db, "user-1")
    assert [e["event_type"] for e in events] == ["approved", "timeout"]


async def test_list_events_scoped_to_user(temp_db):
    await audit.log_event(temp_db, "user-1", "req-1", "approved")
    await audit.log_event(temp_db, "user-2", "req-2", "rejected")
    assert len(await audit.list_events(temp_db, "user-1")) == 1
    assert len(await audit.list_events(temp_db, "user-2")) == 1


async def test_list_events_respects_limit(temp_db):
    for i in range(5):
        await audit.log_event(temp_db, "user-1", f"req-{i}", "timeout")
    assert len(await audit.list_events(temp_db, "user-1", limit=2)) == 2
