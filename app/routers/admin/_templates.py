"""Shared Jinja2Templates instance for every /admin/* page."""
from datetime import datetime

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def _local_datetime(value: str) -> str:
    # Audit rows are stored as datetime.now(timezone.utc).isoformat() — show
    # them in the container's own local time (TZ env var), not a raw UTC
    # string with microseconds nobody asked to read.
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


templates.env.filters["local_datetime"] = _local_datetime
