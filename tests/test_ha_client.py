"""Reachability tracking: what /health and the startup path read."""
import httpx
import pytest

from app import ha_client


async def test_reachability_follows_what_home_assistant_last_answered(monkeypatch):
    monkeypatch.setattr(ha_client, "_rest_healthy", False)
    monkeypatch.setattr(ha_client, "is_ws_healthy", lambda: False)

    answer = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        if answer["status"] == 0:
            raise httpx.ConnectError("nope")
        return httpx.Response(answer["status"], json={"message": "API running."})

    fake = httpx.AsyncClient(
        base_url="http://ha.test",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(ha_client, "_client", fake)
    try:
        await ha_client.validate_connectivity()
        assert ha_client.is_ha_reachable() is True

        answer["status"] = 0
        with pytest.raises(httpx.ConnectError):
            await ha_client.validate_connectivity()
        assert ha_client.is_ha_reachable() is False

        answer["status"] = 200
        await ha_client.validate_connectivity()
        assert ha_client.is_ha_reachable() is True
    finally:
        await fake.aclose()


async def test_a_live_socket_counts_as_reachable(monkeypatch):
    """Events flowing prove the same instance is up, whatever the last GET said."""
    monkeypatch.setattr(ha_client, "_rest_healthy", False)
    monkeypatch.setattr(ha_client, "is_ws_healthy", lambda: True)
    assert ha_client.is_ha_reachable() is True
