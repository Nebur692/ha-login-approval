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
    assert len(used) == 20, sorted(used)
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


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_sign_in_problem_has_its_words_and_code(lang):
    from app import messages

    problems = messages.bridge_problems(lang)
    assert len(problems) == 11
    for name, p in problems.items():
        assert p["message"] and p["act"] and "burburito" in p["footer"].lower(), name
        assert re.fullmatch(r"003-002-\d{3}-\d{3}", p["code"]), name
    assert len({p["code"] for p in problems.values()}) == 11
    assert problems["send_failed"]["act"] == ("SÍ tienes que hacer algo." if lang == "es" else "You DO need to do something.")


@pytest.mark.parametrize("remaining,ever,code", [(0, False, "003-003-042-100"), (0, True, "003-003-042-141"), (2, True, "003-003-042-140")])
@pytest.mark.parametrize("lang,label", [("es", "Código burburito"), ("en", "Burburito code"), ("de", "Burburito code")])
def test_recovery_warnings_end_with_their_code(remaining, ever, code, lang, label):
    from app import messages

    body = messages.recovery_warning_notification(lang, remaining, ever_generated=ever)["body"]
    assert body.endswith(f"{label}: {code}")
    assert "burburito" in body.lower().split(label.lower())[0]
