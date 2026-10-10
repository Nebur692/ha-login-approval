"""Security headers on every response.

The pages here are the ones that approve a sign-in, so what a browser is
allowed to do on them is kept as narrow as the pages themselves need:

- CSP: nothing loads from anywhere but this service, and the only scripts and
  style blocks that run are the ones carrying this response's nonce — so an
  injected <script> does nothing even if escaping were ever missed somewhere.
  Templates read the nonce as `request.state.csp_nonce`.
- No framing (clickjacking an Approve button), no MIME sniffing, no Referer
  (the redirect back to the relying party carries the authorization code).
- `no-store` on everything but the few responses meant to be cached: tokens
  must never be cached (RFC 6749 §5.1), nor pages showing an audit log.
- HSTS only when this service is published over HTTPS, and without
  includeSubDomains: the other hosts under the same domain are not ours to
  decide for.
"""
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings

# Public, identical for everyone, and fetched by relying parties and browsers
# over and over: caching these is the point.
_CACHEABLE_PREFIXES = ("/.well-known/", "/jwks.json", "/branding/")

_HSTS_MAX_AGE = 31536000


def _csp(nonce: str) -> str:
    return "; ".join([
        "default-src 'none'",
        f"script-src 'nonce-{nonce}'",
        f"style-src 'nonce-{nonce}'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)

        headers = response.headers
        headers["Content-Security-Policy"] = _csp(nonce)
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith(_CACHEABLE_PREFIXES):
            headers["Cache-Control"] = "no-store"
        if settings.idp_issuer_url.lower().startswith("https://"):
            headers["Strict-Transport-Security"] = f"max-age={_HSTS_MAX_AGE}"
        return response
