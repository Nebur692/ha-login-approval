"""HTTP Basic Auth dependency shared by every /admin/* sub-router — a tiny,
low-traffic internal tool, not worth a full session/cookie system.
Returns the username on success so callers can record who did what
(recovery-code generation, manual IP unblocks)."""
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    # Compared as bytes: on str, compare_digest raises TypeError the moment a
    # credential contains a non-ASCII character, so a password with an accent
    # in it would turn every login into a 500 instead of a 401.
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), settings.admin_username.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), settings.admin_password.encode("utf-8")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username
