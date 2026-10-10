import asyncio
import json

import httpx
import pytest

from app import target_app
from app.config import settings

# Shapes copied from a real ZITADEL v4.19 event store (IDs and names changed):
# the intent's successURL is Go's url.URL struct, the login request uses
# snake_case keys, and the app events use camelCase.
STATE = "390000000000000001"
REQUEST_ID = "V2_390000000000000002"
CLIENT_ID = "390000000000000003"
APP_ID = "390000000000000004"

INTENT_STARTED = {
    "successURL": {
        "ForceQuery": False, "Fragment": "", "Host": "sso.example.com", "OmitHost": False, "Opaque": "",
        "Path": "/ui/v2/login/idp/oidc/process", "RawFragment": "", "RawPath": "",
        "RawQuery": f"userId=1&requestId=oidc_{REQUEST_ID}&organization=2",
        "Scheme": "https", "User": None,
    },
    "failureURL": {"Path": "/ui/v2/login/idp/oidc/failure", "RawQuery": f"requestId=oidc_{REQUEST_ID}"},
    "idpId": "390000000000000009",
}
AUTH_REQUEST_ADDED = {
    "client_id": CLIENT_ID,
    "redirect_uri": "https://admin.example.com/",
    "issuer": "https://sso.example.com",
    "login_hint": "someone@example.com",
}


def _app_events(*extra):
    return [
        {"type": {"type": "project.application.added"}, "payload": {"appId": APP_ID, "name": "Admin portal"}},
        {"type": {"type": "project.application.config.oidc.added"},
         "payload": {"appId": APP_ID, "clientId": CLIENT_ID, "responseTypes": [0]}},
        *extra,
    ]


class FakeZitadel:
    def __init__(self, *, intent=INTENT_STARTED, auth_request=AUTH_REQUEST_ADDED, apps=None, fail=None):
        self.intent = intent
        self.auth_request = auth_request
        self.apps = _app_events() if apps is None else apps
        self.fail = fail
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.fail == "500":
            return httpx.Response(500)
        if path == "/oauth/v2/token":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 43199})
        assert request.headers["authorization"] == "Bearer tok"
        query = json.loads(request.content)
        if query.get("aggregateId") == STATE and query["eventTypes"] == ["idpintent.started"]:
            return httpx.Response(200, json={"events": [{"payload": self.intent}] if self.intent else []})
        if query.get("aggregateId") == REQUEST_ID and query["eventTypes"] == ["auth_request.added"]:
            return httpx.Response(200, json={"events": [{"payload": self.auth_request}] if self.auth_request else []})
        if query.get("aggregateTypes") == ["project"]:
            return httpx.Response(200, json={"events": self.apps})
        return httpx.Response(200, json={})


@pytest.fixture
def zitadel(monkeypatch):
    monkeypatch.setattr(settings, "zitadel_api_url", "https://sso.example.com/")
    monkeypatch.setattr(settings, "zitadel_api_client_id", "reader")
    monkeypatch.setattr(settings, "zitadel_api_client_secret", "reader-secret")
    monkeypatch.setattr(target_app, "_token", None)
    monkeypatch.setattr(target_app, "_token_expires_at", 0.0)
    monkeypatch.setattr(target_app, "_apps_loaded_at", 0.0)
    monkeypatch.setattr(target_app, "_app_names", {})
    fake = FakeZitadel()
    monkeypatch.setattr(target_app, "_transport", httpx.MockTransport(fake.handler))
    return fake


async def test_names_the_app_and_its_host(zitadel):
    app = await target_app.resolve(STATE)
    assert app == target_app.TargetApp(name="Admin portal", host="admin.example.com")
    assert app.label() == "Admin portal (admin.example.com)"


async def test_not_configured_asks_nobody(zitadel, monkeypatch):
    monkeypatch.setattr(settings, "zitadel_api_client_secret", "")
    assert await target_app.resolve(STATE) is None
    assert zitadel.calls == []


@pytest.mark.parametrize("state", ["", "xyz", "3904 1", "1" * 33, "12&aggregateId=3"])
async def test_a_state_that_is_not_a_zitadel_id_asks_nobody(zitadel, state):
    assert await target_app.resolve(state) is None
    assert zitadel.calls == []


async def test_renamed_app_shows_its_current_name(zitadel):
    zitadel.apps = _app_events(
        {"type": {"type": "project.application.changed"}, "payload": {"appId": APP_ID, "name": "Admin v2"}},
    )
    assert (await target_app.resolve(STATE)).name == "Admin v2"


async def test_removed_app_falls_back_to_the_host(zitadel):
    zitadel.apps = _app_events({"type": {"type": "project.application.removed"}, "payload": {"appId": APP_ID}})
    app = await target_app.resolve(STATE)
    assert app == target_app.TargetApp(name=None, host="admin.example.com")
    assert app.label() == "admin.example.com"


async def test_several_apps_pick_the_one_of_this_login(zitadel):
    zitadel.apps = [
        {"type": {"type": "project.application.added"}, "payload": {"appId": "a1", "name": "Other"}},
        {"type": {"type": "project.application.config.oidc.added"}, "payload": {"appId": "a1", "clientId": "c1"}},
        *_app_events(),
        {"type": {"type": "project.application.added"}, "payload": {"appId": "a3", "name": "Third"}},
    ]
    assert (await target_app.resolve(STATE)).name == "Admin portal"


async def test_app_list_is_loaded_once_not_per_login(zitadel):
    await target_app.resolve(STATE)
    await target_app.resolve(STATE)
    assert zitadel.calls.count("/oauth/v2/token") == 1
    project_reads = [c for c in zitadel.calls if c == "/admin/v1/events/_search"]
    # two logins x (intent + request) + a single app-list read
    assert len(project_reads) == 5


async def test_unknown_client_id_does_not_reload_the_list_every_login(zitadel):
    zitadel.apps = []
    await target_app.resolve(STATE)
    await target_app.resolve(STATE)
    assert len([c for c in zitadel.calls if c == "/admin/v1/events/_search"]) == 5


async def test_success_url_as_a_plain_string_is_understood(zitadel):
    zitadel.intent = {"successURL": f"https://sso.example.com/process?requestId=oidc_{REQUEST_ID}"}
    assert (await target_app.resolve(STATE)).name == "Admin portal"


async def test_saml_login_has_no_app_line(zitadel):
    zitadel.intent = {"successURL": {"RawQuery": "requestId=saml_V2_1"}}
    assert await target_app.resolve(STATE) is None


async def test_unknown_intent_has_no_app_line(zitadel):
    zitadel.intent = None
    assert await target_app.resolve(STATE) is None


async def test_zitadel_failing_never_raises(zitadel):
    zitadel.fail = "500"
    assert await target_app.resolve(STATE) is None


async def test_zitadel_hanging_gives_up_in_time(zitadel, monkeypatch):
    async def hang(request):
        await asyncio.sleep(10)

    class Hanging(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await hang(request)

    monkeypatch.setattr(target_app, "_transport", Hanging())
    monkeypatch.setattr(target_app, "_LOOKUP_TIMEOUT_SECONDS", 0.05)
    assert await target_app.resolve(STATE) is None
