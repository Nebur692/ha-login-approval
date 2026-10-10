"""Burburito codes: the footer every error a person sees ends with.

A light-hearted line, picked at random, and a `Burburito code` —
PPP-MMM-AAA-CCC: project, module, what the person was trying to do, and why it
failed. Whoever hits an error only has to pass that line on: the code says
where to look, with no logs and no screenshots.

Reads only burburito.lock.json next to this file, generated from
burburito.json (the catalogue's source). No database, no network: an error
message has to come out even when everything else is down. And nothing here
may raise — a failure inside the error reporter would leave the person with
no message at all.
"""
import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

UNCATALOGUED = "000-000-000-000"
_LOCK = Path(__file__).with_name("burburito.lock.json")
_EMERGENCY = {
    "es": "Algo se ha quemado en las cocinas de Burbujalandia y ni siquiera sé qué burburito ha sido.",
    "en": "Something got burnt in the kitchens of Burbujalandia and I do not even know which burburito did it.",
}
_EMOJI = {"aviso": "🫧", "error": "🍳", "catastrofe": "🔥"}


def _load() -> dict:
    try:
        return json.loads(_LOCK.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Could not read %s: %s", _LOCK, exc)
        return {"codigos": {}, "frases": {}}


_lock = _load()


def _entry(key: str) -> dict:
    entry = (_lock.get("codigos") or {}).get(key)
    if isinstance(entry, dict) and entry.get("codigo"):
        return entry
    logger.error("Burburito key not in the catalogue: %s", key)
    return {"codigo": UNCATALOGUED, "severidad": "error", "actuar": True}


def footer(key: str, lang: str = "en") -> dict:
    """{code, severity, act, text} for this key, in `lang` ("es" or "en").
    `act` answers the question every message must answer: does the reader
    need to do something? The joke goes last; it is never the diagnosis."""
    try:
        lang = "es" if lang == "es" else "en"
        entry = _entry(key)
        severity = entry.get("severidad", "error")
        phrases = (_lock.get("frases") or {}).get(severity) or []
        chosen = random.choice(phrases) if phrases else {}
        line = chosen.get(lang) or chosen.get("es") or _EMERGENCY[lang]
        return {
            "code": entry["codigo"],
            "severity": severity,
            "act": bool(entry.get("actuar")),
            "text": f"{_EMOJI.get(severity, '🍳')} {line}",
            "label": "Código burburito" if lang == "es" else "Burburito code",
        }
    except Exception as exc:
        logger.error("Burburito footer failed for %s: %s", key, exc)
        return {"code": UNCATALOGUED, "severity": "error", "act": True, "text": _EMERGENCY["en"], "label": "Burburito code"}


def known_keys() -> set[str]:
    return set((_lock.get("codigos") or {}).keys())
