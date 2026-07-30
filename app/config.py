"""Application settings, loaded from environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Home Assistant
    ha_base_url: str
    ha_token: str

    # ZITADEL — only needed for the legacy Actions V2 webhook
    # (routers/webhook.py), which is inherently ZITADEL-specific and
    # entirely optional. Left unconfigured, that webhook and its
    # ZITADEL-specific admin page (devices.py) are simply not registered —
    # the passwordless OIDC provider (routers/idp.py) doesn't need any of
    # this to work with ZITADEL, Keycloak, Authentik, or any other RP.
    zitadel_base_url: str = ""
    zitadel_client_id: str = ""
    zitadel_client_secret: str = ""
    zitadel_target_signing_key: str = ""
    """Signing key ZITADEL returned when the webhook Target was created —
    used to verify the `zitadel-signature` header on incoming requests."""

    # Admin panel (HTTP Basic Auth — small internal tool, few users)
    admin_username: str = "admin"
    admin_password: str

    # Approval flow
    approval_timeout_seconds: int = 120
    """Must stay comfortably below ZITADEL's own 270s Action target timeout."""

    metadata_key: str = "ha_notify_targets"

    # v2.0.0 storage — recovery codes, audit log, IP-block state, branding
    # (ha_notify_targets stays in ZITADEL metadata, unaffected by this)
    sqlite_db_path: str = "/data/ha-login-approval.db"

    # v2.0.0 passwordless OIDC provider — this service acts as a generic
    # external IDP for ZITADEL (and, per README, any OIDC-capable RP).
    idp_issuer_url: str = ""
    """Our own public base URL, e.g. https://ha-login.example.com — used as
    the `iss` claim and to build the discovery document's endpoint URLs."""
    idp_client_id: str = ""
    """Client ID the relying party (e.g. ZITADEL) authenticates with against
    our /token endpoint. Single static client for v2.0.0 — one RP per
    deployment, matching this project's single-tenant scope."""
    idp_client_secret: str = ""
    idp_client_redirect_uri: str = ""
    """Exact redirect_uri the RP will use — validated on every /authorize
    call to prevent an open redirect via a forged redirect_uri."""
    idp_login_timeout_seconds: int = 300
    """How long a pending /authorize request stays valid waiting for the
    email + approval steps on the bridge page."""
    bridge_recovery_unlock_delay_seconds: int = 60
    """How long the bridge page waits with no response before offering
    retry/recovery-code options — independent of approval_timeout_seconds
    (the backend keeps waiting for the real HA response up to that longer
    timeout regardless of whether this UI escalation has kicked in)."""

    # v2.0.0 anti-abuse
    ip_block_threshold: int = 3
    """Consecutive failures (explicit rejects + wrong recovery codes, same
    account + same IP) before blocking — not a time-window rate limit."""
    recovery_code_batch_size: int = 10
    recovery_code_low_warning: int = 3
    """Warn when this many or fewer unused codes remain."""

    # v2.0.0 GeoIP enrichment (self-hosted MaxMind GeoLite2, optional)
    geoip_account_id: str = ""
    geoip_license_key: str = ""
    """Free MaxMind account required — see README. Left empty, GeoIP
    enrichment is simply skipped (city/country/ISP fields stay empty in
    the audit log), it's not required for the login flow to work."""
    geoip_db_dir: str = "/data/geoip"

    # v2.0.0 admin panel additions
    branding_asset_dir: str = "/data/branding"
    """Where uploaded logo/background/favicon files are stored — only
    their path lives in the bridge_branding table, keeping the SQLite file
    itself small and a simple single-file backup."""


settings = Settings()
