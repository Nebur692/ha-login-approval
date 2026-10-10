"""The dependency every /admin/* page uses: a live session (admin_sessions.py),
and on anything that changes state, that session's CSRF token.

Returns the username, so callers can record who did what. Without a session,
a page visit is sent to the sign-in page and anything else is refused.
"""
import secrets
from urllib.parse import quote

from fastapi import HTTPException, Request

from app import admin_sessions
from app.config import settings

_SAFE_METHODS = {"GET", "HEAD"}


def cookie_name() -> str:
    # The __Host- prefix makes the browser refuse the cookie unless it is
    # Secure, host-only and Path=/ — so it cannot be planted from a sibling
    # subdomain. It needs HTTPS, so plain-HTTP setups use a plain name.
    return "__Host-hla_admin" if secure_cookies() else "hla_admin"


def secure_cookies() -> bool:
    return settings.idp_issuer_url.lower().startswith("https://")


async def require_admin(request: Request) -> str:
    session = await admin_sessions.lookup(request.cookies.get(cookie_name()))
    if session is None:
        if request.method in _SAFE_METHODS:
            raise HTTPException(
                status_code=303,
                headers={"Location": f"/admin/login?next={quote(request.url.path)}"},
            )
        raise HTTPException(status_code=403, detail="Not signed in")

    if request.method not in _SAFE_METHODS:
        form = await request.form()
        sent = form.get("csrf_token")
        if not isinstance(sent, str) or not secrets.compare_digest(sent, session["csrf_token"]):
            raise HTTPException(status_code=403, detail="Missing or wrong CSRF token")

    request.state.admin_user = session["username"]
    request.state.csrf_token = session["csrf_token"]
    request.state.session_hash = session["token_hash"]
    return session["username"]
