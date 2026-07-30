"""ha-login-approval — FastAPI entry point.

Two independent flows can be enabled: the generic passwordless OIDC
provider (routers/idp.py, v2.0.0 — works with ZITADEL, Keycloak, Authentik,
or any standard OIDC relying party) and the legacy ZITADEL Actions V2
webhook (routers/webhook.py, v1.0.0 — inherently ZITADEL-specific, entirely
optional). ZITADEL connectivity is only initialized/validated, and the
webhook router only registered, if ZITADEL_BASE_URL is actually configured
— a deployment that only wants the passwordless flow with a different RP
doesn't need to configure ZITADEL at all.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, geoip_updater, ha_client, idp_jwt, zitadel_client
from app.config import settings
from app.routers import admin, idp, webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ZITADEL_ENABLED = bool(settings.zitadel_base_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ha_client.init_client()
    await db.init_db()
    await idp_jwt.ensure_signing_key()
    await geoip_updater.start_periodic_updater()
    await ha_client.validate_connectivity()

    if ZITADEL_ENABLED:
        zitadel_client.init_client()
        await zitadel_client.validate_connectivity()
    else:
        logger.info("ZITADEL_BASE_URL not configured — legacy Actions V2 webhook disabled")

    await ha_client.start_ws_listener()

    yield

    await ha_client.stop_ws_listener()
    await ha_client.close_client()
    if ZITADEL_ENABLED:
        await zitadel_client.close_client()
    await geoip_updater.stop_periodic_updater()
    await db.close_db()


app = FastAPI(title="ha-login-approval", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(admin.router)
app.include_router(idp.router)
if ZITADEL_ENABLED:
    app.include_router(webhook.router)


@app.get("/health")
async def health():
    return {"status": "ok", "ha_ws": "connected" if ha_client.is_ws_healthy() else "disconnected"}
