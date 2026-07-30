"""Shared Jinja2Templates instance for every /admin/* page — carries the
`zitadel_enabled` global so base.html can hide the legacy "Devices" nav
link when ZITADEL isn't configured (see main.py/__init__.py)."""
from fastapi.templating import Jinja2Templates

from app.config import settings

templates = Jinja2Templates(directory="templates")
templates.env.globals["zitadel_enabled"] = bool(settings.zitadel_base_url)
