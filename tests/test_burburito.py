import json
import re
from pathlib import Path

import pytest

from app import burburito

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"""["']([a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+)["']""")
CATALOGUE = json.loads((ROOT / "app" / "burburito.json").read_text())
LOCK = json.loads((ROOT / "app" / "burburito.lock.json").read_text())


def _keys_used_in_the_code() -> set[str]:
    found = set()
    for path in [*ROOT.joinpath("app").rglob("*.py"), ROOT / "main.py"]:
        for key in KEY.findall(path.read_text()):
            if key.split("/")[0] in {m["slug"] for m in CATALOGUE["modulos"]}:
                found.add(key)
    return found


def test_every_key_in_the_code_is_catalogued():
    used = _keys_used_in_the_code()
    # The total, not just "none bad": an empty scan would pass that vacuously.
    assert len(used) == 6, sorted(used)
    missing = used - burburito.known_keys()
    assert not missing, missing
    for key in used:
        assert burburito.footer(key)["code"] != burburito.UNCATALOGUED


def test_the_lock_matches_its_catalogue():
    in_catalogue = {f"{c['modulo']}/{c['accion']}/{c['causa']}" for c in CATALOGUE["codigos"]}
    assert in_catalogue == set(LOCK["codigos"]), "run: bin/burburito sincroniza app/burburito.json"


def test_codes_are_deterministic_and_well_formed():
    for key in burburito.known_keys():
        codes = {burburito.footer(key)["code"] for _ in range(20)}
        assert len(codes) == 1
        assert re.fullmatch(r"003-\d{3}-\d{3}-\d{3}", codes.pop())


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_phrase_says_burburito(lang):
    for severity, phrases in LOCK["frases"].items():
        assert phrases, severity
        for phrase in phrases:
            assert "burburito" in phrase[lang].lower(), phrase


def test_footer_speaks_the_readers_language():
    key = "panel/iniciar-sesion/credencial-invalida"
    assert burburito.footer(key, "es")["label"] == "Código burburito"
    assert burburito.footer(key, "en")["label"] == "Burburito code"


def test_an_unknown_key_or_a_missing_lock_still_gives_a_footer(monkeypatch):
    assert burburito.footer("panel/no-such/thing")["code"] == burburito.UNCATALOGUED
    monkeypatch.setattr(burburito, "_lock", {})
    out = burburito.footer("panel/iniciar-sesion/credencial-invalida")
    assert out["code"] == burburito.UNCATALOGUED and "burburito" in out["text"]
