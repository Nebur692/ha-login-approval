import re
from pathlib import Path

import pytest

from app import db, idp_jwt
from app.config import settings
from tests.conftest import sign_in
CLIENT_ID = "test-rp"
REDIRECT_URI = "https://rp.test/idps/callback"


@pytest.fixture
async def idp_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "h.db"))
    monkeypatch.setattr(settings, "idp_issuer_url", "http://ha-login.test")
    monkeypatch.setattr(settings, "idp_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "idp_client_redirect_uri", REDIRECT_URI)
    await db.init_db()
    await idp_jwt.ensure_signing_key()
    yield
    await db.close_db()


def _authorize_params():
    return {"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code", "state": "xyz"}

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _nonce(resp) -> str:
    csp = resp.headers["content-security-policy"]
    match = re.search(r"script-src 'nonce-([^']+)'", csp)
    assert match, csp
    assert f"style-src 'nonce-{match.group(1)}'" in csp
    return match.group(1)


async def test_bridge_page_scripts_and_styles_carry_this_responses_nonce(client, idp_ready):
    resp = await client.get("/authorize", params=_authorize_params())
    nonce = _nonce(resp)
    tags = re.findall(r"<(script|style)\b([^>]*)>", resp.text)
    assert tags, "the page has no script/style at all — the test would prove nothing"
    for name, attrs in tags:
        assert f'nonce="{nonce}"' in attrs, f"<{name}{attrs}> would be blocked by the CSP"


async def test_each_response_gets_a_fresh_nonce(client, idp_ready):
    first = _nonce(await client.get("/authorize", params=_authorize_params()))
    second = _nonce(await client.get("/authorize", params=_authorize_params()))
    assert first != second


@pytest.mark.parametrize("path", ["/admin", "/admin/audit", "/admin/signing-key"])
async def test_admin_pages_carry_the_nonce(client, idp_ready, path, monkeypatch):
    await sign_in(client, monkeypatch)
    resp = await client.get(path)
    assert resp.status_code == 200
    nonce = _nonce(resp)
    for name, attrs in re.findall(r"<(script|style)\b([^>]*)>", resp.text):
        assert f'nonce="{nonce}"' in attrs


@pytest.mark.parametrize("template", sorted(p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*.html")))
def test_no_template_relies_on_what_the_csp_blocks(template):
    """Inline style="" and on*="" handlers have no nonce to carry: under this
    CSP the browser drops them silently, so the page just looks or behaves
    wrong with nothing in any log."""
    text = (TEMPLATES / template).read_text()
    assert not re.search(r"\sstyle\s*=", text), "style attribute"
    assert not re.search(r"\son[a-z]+\s*=", text), "inline event handler"
    for name, attrs in re.findall(r"<(script|style)\b([^>]*)>", text):
        assert "csp_nonce" in attrs, f"<{name}> without the nonce"


async def test_basic_headers_everywhere(client, idp_ready):
    for path in ["/authorize?" + "&".join(f"{k}={v}" for k, v in _authorize_params().items()), "/jwks.json", "/health"]:
        headers = (await client.get(path)).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]


async def test_token_and_pages_are_not_cached_but_public_documents_are(client, idp_ready):
    token = await client.post("/token", data={"grant_type": "authorization_code", "code": "x"})
    assert token.headers["cache-control"] == "no-store"
    page = await client.get("/authorize", params=_authorize_params())
    assert page.headers["cache-control"] == "no-store"
    for path in ["/jwks.json", "/.well-known/openid-configuration"]:
        assert "cache-control" not in (await client.get(path)).headers


async def test_hsts_only_when_published_over_https(client, idp_ready, monkeypatch):
    assert "strict-transport-security" not in (await client.get("/jwks.json")).headers
    monkeypatch.setattr(settings, "idp_issuer_url", "https://ha-login.example.com")
    hsts = (await client.get("/jwks.json")).headers["strict-transport-security"]
    assert hsts == "max-age=31536000"
