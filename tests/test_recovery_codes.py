import pytest

from app import db, recovery_codes
from app.config import settings

USER = "user-1"


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "recovery.db"))
    await db.init_db()
    yield db.get_db()
    await db.close_db()


async def test_generate_batch_returns_plaintext_codes_not_stored_in_plaintext(temp_db):
    codes = await recovery_codes.generate_batch(temp_db, USER, generated_by="admin", count=5)
    assert len(codes) == 5
    assert len(set(codes)) == 5  # no duplicates in one batch

    cursor = await temp_db.execute("SELECT code_hash FROM recovery_codes WHERE zitadel_user_id = ?", (USER,))
    rows = await cursor.fetchall()
    stored_hashes = {r["code_hash"] for r in rows}
    assert not (stored_hashes & set(codes))  # plaintext never stored as-is


async def test_verify_correct_code_succeeds_once(temp_db):
    codes = await recovery_codes.generate_batch(temp_db, USER, generated_by="admin", count=3)
    code = codes[0]

    assert await recovery_codes.verify_code(temp_db, USER, code, used_ip="1.2.3.4") is True
    # Reusing the same code must fail — one-time use.
    assert await recovery_codes.verify_code(temp_db, USER, code, used_ip="1.2.3.4") is False


async def test_verify_wrong_code_fails(temp_db):
    await recovery_codes.generate_batch(temp_db, USER, generated_by="admin", count=3)
    assert await recovery_codes.verify_code(temp_db, USER, "AAAA-AAAA-AAAA", used_ip="1.2.3.4") is False


async def test_verify_with_no_codes_generated_fails(temp_db):
    assert await recovery_codes.verify_code(temp_db, "no-such-user", "AAAA-AAAA-AAAA", used_ip="1.2.3.4") is False


async def test_regenerate_invalidates_previous_generation(temp_db):
    first_batch = await recovery_codes.generate_batch(temp_db, USER, generated_by="admin", count=3)
    second_batch = await recovery_codes.generate_batch(temp_db, USER, generated_by="admin", count=3)

    # An old code from the first batch must no longer work...
    assert await recovery_codes.verify_code(temp_db, USER, first_batch[0], used_ip="1.2.3.4") is False
    # ...while a code from the new batch does.
    assert await recovery_codes.verify_code(temp_db, USER, second_batch[0], used_ip="1.2.3.4") is True


async def test_remaining_count_decrements_on_use(temp_db):
    codes = await recovery_codes.generate_batch(temp_db, USER, generated_by="admin", count=4)
    assert await recovery_codes.remaining_count(temp_db, USER) == 4

    await recovery_codes.verify_code(temp_db, USER, codes[0], used_ip="1.2.3.4")
    assert await recovery_codes.remaining_count(temp_db, USER) == 3


async def test_remaining_count_zero_for_unknown_user(temp_db):
    assert await recovery_codes.remaining_count(temp_db, "no-such-user") == 0
