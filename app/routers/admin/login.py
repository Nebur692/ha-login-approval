"""Sign in to and out of the admin panel (admin_sessions.py)."""
import asyncio
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import admin_sessions, client_ip
from app.routers.admin._auth import cookie_name, require_admin, secure_cookies
from app.routers.admin._templates import templates

router = APIRouter()

# Every sign-in answer takes at least this long, right or wrong, so how long
# it took says nothing about why — and each guess costs the guesser a second.
_MIN_ANSWER_SECONDS = 1.0


def _safe_next(next_path: str) -> str:
    # Only somewhere inside the panel: anything else would make this page an
    # open redirect ("//evil.example" is a full URL to a browser).
    if next_path.startswith("/admin") and not next_path.startswith("//"):
        return next_path
    return "/admin"


def _login_page(request: Request, next_path: str, error: str | None, status_code: int = 200):
    return templates.TemplateResponse(request, "admin/login.html", {
        "next": _safe_next(next_path),
        "error": error,
        "password_problem": admin_sessions.password_problem(),
    }, status_code=status_code)


@router.get("/admin/login")
async def login_page(request: Request, next: str = "/admin"):
    return _login_page(request, next, None)


@router.post("/admin/login")
async def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/admin"),
):
    started = time.monotonic()
    ip = client_ip.resolve(request)
    try:
        if admin_sessions.password_problem():
            await admin_sessions.record(admin_sessions.LOGIN_REFUSED, username=username, ip=ip, detail="weak password")
            return _login_page(request, next, None, status_code=403)
        if await admin_sessions.too_many_failures(ip):
            await admin_sessions.record(admin_sessions.LOGIN_REFUSED, username=username, ip=ip, detail="too many failures")
            return _login_page(request, next, "Too many failed attempts. Try again in 15 minutes.", status_code=429)
        if not admin_sessions.credentials_match(username, password):
            await admin_sessions.record(admin_sessions.LOGIN_FAILED, username=username, ip=ip)
            return _login_page(request, next, "Wrong username or password.", status_code=401)

        token = await admin_sessions.create(username, ip, request.headers.get("user-agent", ""))
        await admin_sessions.record(admin_sessions.LOGIN_OK, username=username, ip=ip)
        response = RedirectResponse(url=_safe_next(next), status_code=303)
        response.set_cookie(
            cookie_name(), token, httponly=True, secure=secure_cookies(), samesite="strict", path="/",
            max_age=int(admin_sessions.ABSOLUTE_TIMEOUT.total_seconds()),
        )
        return response
    finally:
        remaining = _MIN_ANSWER_SECONDS - (time.monotonic() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)


@router.post("/admin/logout")
async def logout(request: Request, admin_user: str = Depends(require_admin)):
    await admin_sessions.end(request.state.session_hash)
    await admin_sessions.record(admin_sessions.LOGOUT, username=admin_user, ip=client_ip.resolve(request))
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(cookie_name(), path="/", secure=secure_cookies(), httponly=True, samesite="strict")
    return response
