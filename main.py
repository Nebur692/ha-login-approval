"""ZITADEL <-> Home Assistant login-approval bridge — FastAPI entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, ha_client, idp_jwt, zitadel_client
from app.routers import admin, idp, webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ha_client.init_client()
    zitadel_client.init_client()
    await db.init_db()
    await idp_jwt.ensure_signing_key()

    await ha_client.validate_connectivity()
    await zitadel_client.validate_connectivity()

    await ha_client.start_ws_listener()

    yield

    await ha_client.stop_ws_listener()
    await ha_client.close_client()
    await zitadel_client.close_client()
    await db.close_db()


app = FastAPI(title="ha-login-approval", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(admin.router)
app.include_router(webhook.router)
app.include_router(idp.router)


@app.get("/health")
async def health():
    return {"status": "ok", "ha_ws": "connected" if ha_client.is_ws_healthy() else "disconnected"}
