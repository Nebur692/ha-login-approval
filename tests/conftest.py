import os

os.environ.setdefault("HA_BASE_URL", "http://ha.test")
os.environ.setdefault("HA_TOKEN", "test-ha-token")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def sign_in(client, monkeypatch, username="admin", password="test-admin-password") -> str:
    """Signs in through the real form, as a person would, and returns the
    session's CSRF token for the forms the test submits. The one-second floor
    on sign-in answers is lifted here; test_admin_sessions measures it."""
    import re

    from app.routers.admin import login

    monkeypatch.setattr(login, "_MIN_ANSWER_SECONDS", 0)
    resp = await client.post("/admin/login", data={"username": username, "password": password})
    assert resp.status_code == 303, resp.text
    page = await client.get("/admin/signing-key")
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
