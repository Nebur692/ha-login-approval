"""Passwordless OIDC provider (v2.0.0): this service acts as a generic
external IDP that ZITADEL (or any OIDC-capable RP) redirects to.

Confirmed empirically against a real ZITADEL instance before writing this
(see Fase 1 of the v2.0.0 plan): `login_hint` never arrives (a known,
still-open ZITADEL bug, and Keycloak's default external-IDP button doesn't
send it either), so /authorize can never assume it knows who's logging in —
the bridge page always collects the email itself. The token endpoint is
authenticated via `client_secret_basic` (confirmed live), and ZITADEL always
calls /userinfo after the token exchange — omitting it makes the whole
login fail, so it's implemented here even though nothing forces us to.

This is Fase 5's minimal functional bridge page (email field + spinner,
polling /idp/status). Fase 6 replaces this with the full UX: 60s escalation
to a retry/recovery-code screen, branding, etc.
"""
import asyncio
import base64
import logging
import time
import uuid

from fastapi import APIRouter, Form, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import idp_jwt, zitadel_client
from app.approval_flow import ApprovalOutcome, LoginContext, run_approval
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# In-memory state, mirroring the pattern already used in ha_client.py's
# _pending futures — a login attempt lives for at most idp_login_timeout_seconds,
# so there's nothing here worth persisting across a restart.
_pending: dict[str, dict] = {}
_auth_codes: dict[str, dict] = {}
_access_tokens: dict[str, dict] = {}


def _issuer() -> str:
    return settings.idp_issuer_url.rstrip("/")


@router.get("/.well-known/openid-configuration")
async def discovery():
    base = _issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "jwks_uri": f"{base}/jwks.json",
        "userinfo_endpoint": f"{base}/userinfo",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [idp_jwt.ALGORITHM],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "claims_supported": ["sub", "email", "email_verified"],
    }


@router.get("/jwks.json")
async def jwks():
    return idp_jwt.get_jwks()


@router.get("/authorize")
async def authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str = "openid",
    state: str = "",
    login_hint: str | None = None,
):
    if client_id != settings.idp_client_id or redirect_uri != settings.idp_client_redirect_uri:
        raise HTTPException(status_code=400, detail="unknown client_id or redirect_uri")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")

    request_id = uuid.uuid4().hex
    _pending[request_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "created_at": time.time(),
        "status": "awaiting_email",
        "email": login_hint,
        "zitadel_user_id": None,
        "ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", ""),
    }

    if login_hint:
        # Kept as a cheap, non-blocking check for forward-compatibility —
        # not expected to trigger with ZITADEL or Keycloak (see Fase 1),
        # but if some RP ever does send it, skip the email step entirely.
        asyncio.create_task(_start_approval(request_id, login_hint))

    return templates.TemplateResponse(request, "idp_bridge.html", {"request_id": request_id})


async def _start_approval(request_id: str, email: str) -> None:
    pending = _pending.get(request_id)
    if pending is None:
        return

    user = await zitadel_client.find_user_by_login(email)
    if user is None:
        pending["status"] = "denied"
        return

    pending["email"] = email
    pending["zitadel_user_id"] = user["id"]
    pending["status"] = "waiting"

    context = LoginContext(ip=pending["ip"], browser_description=pending["user_agent"])
    outcome = await run_approval(user["id"], request_id, context)

    # Unlike the legacy webhook (routers/webhook.py), NO_TARGETS must deny
    # here — there is no password fallback in this flow, so an account with
    # no HA devices assigned can never complete a passwordless login.
    pending["status"] = {
        ApprovalOutcome.APPROVED: "approved",
        ApprovalOutcome.REJECTED: "rejected",
        ApprovalOutcome.TIMEOUT: "timeout",
        ApprovalOutcome.NO_TARGETS: "denied",
    }[outcome]


@router.post("/idp/email")
async def submit_email(request_id: str = Form(...), email: str = Form(...)):
    pending = _pending.get(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="unknown or expired request")
    if pending["status"] != "awaiting_email":
        raise HTTPException(status_code=409, detail="email already submitted for this request")

    pending["status"] = "resolving"
    asyncio.create_task(_start_approval(request_id, email))
    return {"status": "resolving"}


@router.get("/idp/status/{request_id}")
async def status(request_id: str):
    pending = _pending.get(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="unknown or expired request")
    return {"status": pending["status"]}


@router.get("/idp/complete/{request_id}")
async def complete(request_id: str):
    pending = _pending.get(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="unknown or expired request")
    if pending["status"] != "approved":
        raise HTTPException(status_code=409, detail="login not approved")

    code = uuid.uuid4().hex
    _auth_codes[code] = {
        "client_id": pending["client_id"],
        "zitadel_user_id": pending["zitadel_user_id"],
        "email": pending["email"],
        "issued_at": time.time(),
    }
    del _pending[request_id]

    qs = f"code={code}&state={pending['state']}"
    return RedirectResponse(url=f"{pending['redirect_uri']}?{qs}", status_code=302)


def _parse_basic_auth(header: str | None) -> tuple[str, str] | None:
    if not header or not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[len("Basic "):]).decode()
        client_id, _, client_secret = decoded.partition(":")
        return client_id, client_secret
    except Exception:
        return None


@router.post("/token")
async def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    authorization: str | None = Header(default=None),
):
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    basic = _parse_basic_auth(authorization)
    if basic:
        client_id, client_secret = basic

    if client_id != settings.idp_client_id or client_secret != settings.idp_client_secret:
        raise HTTPException(status_code=401, detail="invalid_client")

    entry = _auth_codes.pop(code, None)
    if entry is None:
        raise HTTPException(status_code=400, detail="invalid_grant")

    id_token = idp_jwt.build_id_token(
        issuer=_issuer(),
        audience=entry["client_id"],
        subject=entry["zitadel_user_id"],
        email=entry["email"],
    )
    access_token = uuid.uuid4().hex
    _access_tokens[access_token] = {"sub": entry["zitadel_user_id"], "email": entry["email"]}
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 300,
        "id_token": id_token,
    }


@router.get("/userinfo")
async def userinfo(authorization: str | None = Header(default=None)):
    # Confirmed live against ZITADEL (Fase 1): it calls this unconditionally
    # after the token exchange and fails the whole login if it 404s or the
    # claims don't include `sub` — so this returns real claims, not a stub.
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    claims = _access_tokens.get(authorization[len("Bearer "):])
    if claims is None:
        raise HTTPException(status_code=401, detail="invalid access token")
    return {"sub": claims["sub"], "email": claims["email"], "email_verified": True}
