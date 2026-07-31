"""Shared Jinja2Templates instance for every /admin/* page."""
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
