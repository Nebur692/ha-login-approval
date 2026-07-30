"""Dataclasses mirroring the tables in app/migrations/0001_init.sql.

Thin representations of DB rows — the modules that own each table
(recovery_codes.py, ip_blocking.py, audit.py, geoip.py, idp_jwt.py) build
these from aiosqlite.Row results rather than callers touching SQL directly.
"""
from dataclasses import dataclass


@dataclass
class RecoveryCodeGeneration:
    zitadel_user_id: str
    current_generation: int
    generated_at: str | None
    generated_by: str | None
    code_count: int | None


@dataclass
class RecoveryCode:
    id: int
    zitadel_user_id: str
    code_hash: str
    generation: int
    created_at: str
    used_at: str | None
    used_ip: str | None


@dataclass
class LoginEvent:
    id: int
    zitadel_user_id: str
    request_id: str
    event_type: str
    occurred_at: str
    ip: str | None
    user_agent: str | None
    geo_city: str | None
    geo_country: str | None
    geo_asn_org: str | None


@dataclass
class IpBlockState:
    zitadel_user_id: str
    ip: str
    consecutive_failures: int
    blocked_at: str | None
    unblocked_at: str | None
    unblocked_by: str | None


@dataclass
class BridgeBranding:
    title: str | None
    logo_path: str | None
    background_path: str | None
    favicon_path: str | None
    updated_at: str | None


@dataclass
class SigningKey:
    id: int
    kid: str
    private_key_pem: str
    public_key_pem: str
    created_at: str
    active: bool
