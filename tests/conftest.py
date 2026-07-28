import os

os.environ.setdefault("HA_BASE_URL", "http://ha.test")
os.environ.setdefault("HA_TOKEN", "test-ha-token")
os.environ.setdefault("ZITADEL_BASE_URL", "https://sso.test")
os.environ.setdefault("ZITADEL_CLIENT_ID", "test-client-id")
os.environ.setdefault("ZITADEL_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ZITADEL_TARGET_SIGNING_KEY", "test-signing-key")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
