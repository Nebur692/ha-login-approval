"""ha-login-approval — FastAPI entry point.

A generic passwordless OIDC provider (routers/idp.py): approve or reject a
sign-in from a Home Assistant push notification, with no password involved
at any point. Works with ZITADEL, Keycloak, Authentik, or any relying
party that supports a generic external OIDC provider.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    await ha_client.validate_connectivity()
    await ha_client.start_ws_listener()

    yield

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
    return {"status": "ok", "ha_ws": "connected" if ha_client.is_ws_healthy() else "disconnected"}
