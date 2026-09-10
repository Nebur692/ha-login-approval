"""ha-login-approval — FastAPI entry point.

A generic passwordless OIDC provider (routers/idp.py): approve or reject a
sign-in from a Home Assistant push notification, with no password involved
at any point. Works with ZITADEL, Keycloak, Authentik, or any relying
party that supports a generic external OIDC provider.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import db, geoip_updater, ha_client, idp_jwt
from app.routers import admin, idp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ha_client.init_client()
    await db.init_db()
    await idp_jwt.ensure_signing_key()
    await geoip_updater.start_periodic_updater()
    await idp.start_periodic_cleanup()

    # Home Assistant being down is not a reason to refuse to start. Both run
    # as ordinary containers with no ordering between them, so a host that
    # reboots can easily bring this one up first; treating that as fatal left
    # the identity provider dead for 7 days (2026-08-11) and again for 15
    # hours (2026-08-21), each time over a boot that was seconds out of order.
    # Nothing served here needs Home Assistant to be up at import time, and
    # the watchdog reconnects on its own once it answers.
    try:
        await ha_client.validate_connectivity()
    except Exception as exc:
        logger.warning(
            "Home Assistant unreachable at startup (%s) — serving anyway, "
            "reconnecting in the background",
            exc,
        )

    connectivity_task = asyncio.create_task(ha_client.connectivity_watchdog())
    connectivity_task.add_done_callback(
        lambda t: logger.error("Connectivity watchdog terminated: %s", t.exception())
        if not t.cancelled() and t.exception() else None
    )

    # Retries by itself with its own backoff, so it is started even while Home
    # Assistant is down.
    await ha_client.start_ws_listener()

    yield

    connectivity_task.cancel()
    await ha_client.stop_ws_listener()
    await ha_client.close_client()
    await idp.stop_periodic_cleanup()
    await geoip_updater.stop_periodic_updater()
    await db.close_db()


app = FastAPI(title="ha-login-approval", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(admin.router)
app.include_router(idp.router)


@app.get("/health")
async def health():
    """Is this container serving? Not: is the whole house working?

    Only what this process owns — its own database — can make it unhealthy.
    Home Assistant being away is reported in the body, but must not turn the
    container red in Docker: that blames the wrong service and would hide a
    real crash here behind an outage next door.

    The failure this is here to catch is the opposite one: uvicorn dying at
    startup while its process lingers, which leaves the container showing
    `Up` with nothing listening. See the container HEALTHCHECK.
    """
    ws_ok = ha_client.is_ws_healthy()
    ha_ok = ha_client.is_ha_reachable()
    try:
        await db.get_db().execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    body = {
        "status": "ok" if (ws_ok and db_ok) else "degraded",
        "ha_ws": "connected" if ws_ok else "disconnected",
        "ha": "reachable" if ha_ok else "unreachable",
        "db": "accessible" if db_ok else "unavailable",
    }
    if db_ok:
        return body
    return JSONResponse(status_code=503, content=body)
