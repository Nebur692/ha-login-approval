"""Shared Jinja2Templates instance for every /admin/* page.

Every page also gets `lang` and `t`, the panel's words in the browser's
language (app/admin_i18n.py)."""
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import admin_i18n


def _i18n(request: Request) -> dict:
    lang = admin_i18n.lang_for(request)
    return {"lang": lang, "t": admin_i18n.STRINGS[lang]}


templates = Jinja2Templates(directory="templates", context_processors=[_i18n])


def _local_datetime(value: str) -> str:
    # Audit rows are stored as datetime.now(timezone.utc).isoformat() — show
    # them in the container's own local time (TZ env var), not a raw UTC
    # string with microseconds nobody asked to read.
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


templates.env.filters["local_datetime"] = _local_datetime
