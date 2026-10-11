import html
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import accounts, admin_i18n, db
from app.config import settings
from tests.conftest import sign_in

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "admin"
ES = {"Accept-Language": "es-ES,es;q=0.9"}
PAGES = ["/admin", "/admin/accounts", "/admin/audit", "/admin/recovery", "/admin/blocked-ips",
         "/admin/branding", "/admin/signing-key", "/admin/activity"]


@pytest.fixture
async def ready(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_db_path", str(tmp_path / "i.db"))
    monkeypatch.setattr(settings, "branding_asset_dir", str(tmp_path / "branding"))
    await db.init_db()
    await sign_in(client, monkeypatch)
    yield
    await db.close_db()


def _flat_keys(d: dict, prefix="") -> set[str]:
    keys = set()
    for k, v in d.items():
        keys |= _flat_keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {prefix + k}
    return keys


def test_both_languages_carry_the_same_words():
    assert _flat_keys(admin_i18n.STRINGS["es"]) == _flat_keys(admin_i18n.STRINGS["en"])


def test_every_word_a_template_or_the_code_asks_for_exists():
    used = set()
    for path in TEMPLATES.glob("*.html"):
        used |= set(re.findall(r"\bt\.([a-z_]+)", path.read_text()))
    # chosen in code and looked up as t[...]
    used |= {"login_locked", "login_wrong", "refused_session", "refused_csrf", "pw_short", "pw_known"}
    assert len(used) > 80
    assert used - set(admin_i18n.STRINGS["en"]) == set()


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_speaks_spanish_to_a_spanish_browser(client, ready, path):
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_x"])):
        es = await client.get(path, headers=ES)
        en = await client.get(path)
    assert es.status_code == en.status_code == 200
    assert '<html lang="es">' in es.text and '<html lang="en">' in en.text
    assert "Cerrar sesión" in es.text and "Sign out" not in es.text
    assert "Sign out" in en.text and "Cerrar sesión" not in en.text


async def test_sign_in_page_and_its_errors_in_spanish(client, ready, monkeypatch):
    from app.routers.admin import login

    monkeypatch.setattr(login, "_MIN_ANSWER_SECONDS", 0)
    page = html.unescape((await client.post("/admin/login", data={"username": "admin", "password": "mal-mal-mal"}, headers=ES)).text)
    assert "Usuario o contraseña incorrectos." in page
    assert "SÍ tienes que hacer algo." in page and "Código burburito: 003-001-001-041" in re.sub("<[^>]+>", "", page)
    monkeypatch.setattr(settings, "admin_password", "corta")
    page = html.unescape((await client.get("/admin/login", headers=ES)).text)
    assert "El panel de administración está apagado: ADMIN_PASSWORD tiene menos de 12 caracteres." in page


async def test_a_refused_change_in_spanish(client, ready):
    resp = await client.post("/admin/accounts/save", data={"email": "x@example.com", "csrf_token": "viejo"}, headers=ES)
    text = html.unescape(resp.text)
    assert resp.status_code == 403
    assert "No se ha cambiado nada" in text and "código de seguridad de tu sesión" in text
    assert "Volver al panel" in text


# --- Accounts: a device the form did not show is never dropped -----------

async def test_a_device_missing_from_home_assistant_is_shown_and_kept(client, ready):
    await accounts.set_targets(db.get_db(), "ana@example.com", ["mobile_app_ana", "mobile_app_tablet"])
    with patch("app.routers.admin.accounts.ha_client.get_notify_targets", AsyncMock(return_value=["mobile_app_ana"])):
        page = html.unescape((await client.get("/admin/accounts")).text)
    card = page[page.index("<h2>ana@example.com</h2>"):]
    assert 'value="mobile_app_tablet" checked' in card
    assert "not in Home Assistant right now" in card


async def test_saving_a_form_that_never_showed_a_device_keeps_it(client, ready, monkeypatch):
    csrf = await sign_in(client, monkeypatch)
    await accounts.set_targets(db.get_db(), "ana@example.com", ["mobile_app_ana", "mobile_app_tablet"])
    # an old page: it only knew mobile_app_ana, and its box is left checked
    await client.post("/admin/accounts/save", data={
        "email": "ana@example.com", "shown": ["mobile_app_ana"], "targets": ["mobile_app_ana"], "csrf_token": csrf,
    })
    assert await accounts.get_targets(db.get_db(), "ana@example.com") == ["mobile_app_ana", "mobile_app_tablet"]


async def test_unchecking_a_shown_device_still_removes_it(client, ready, monkeypatch):
    csrf = await sign_in(client, monkeypatch)
    await accounts.set_targets(db.get_db(), "ana@example.com", ["mobile_app_ana", "mobile_app_tablet"])
    await client.post("/admin/accounts/save", data={
        "email": "ana@example.com", "shown": ["mobile_app_ana", "mobile_app_tablet"], "targets": ["mobile_app_ana"],
        "csrf_token": csrf,
    })
    assert await accounts.get_targets(db.get_db(), "ana@example.com") == ["mobile_app_ana"]
    await client.post("/admin/accounts/save", data={
        "email": "ana@example.com", "shown": ["mobile_app_ana"], "csrf_token": csrf,
    })
    assert await accounts.get_targets(db.get_db(), "ana@example.com") == []
