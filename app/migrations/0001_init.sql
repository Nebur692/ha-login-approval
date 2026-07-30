-- Passwordless v2.0.0: state ZITADEL's per-user metadata API is a poor fit for
-- (unbounded/queryable rows, atomic counters, or config not scoped to a user).
-- ha_notify_targets (device assignment) stays in ZITADEL metadata, untouched.

CREATE TABLE recovery_code_generations (
    zitadel_user_id TEXT PRIMARY KEY,
    current_generation INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT,
    generated_by TEXT,
    code_count INTEGER
);

CREATE TABLE recovery_codes (
    id INTEGER PRIMARY KEY,
    zitadel_user_id TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    generation INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT,
    used_ip TEXT
);
CREATE INDEX idx_recovery_codes_user_gen ON recovery_codes(zitadel_user_id, generation);

CREATE TABLE login_events (
    id INTEGER PRIMARY KEY,
    zitadel_user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN
        ('approved', 'rejected', 'timeout', 'recovery_code_used', 'send_failed', 'blocked')),
    occurred_at TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    geo_city TEXT,
    geo_country TEXT,
    geo_asn_org TEXT
);
CREATE INDEX idx_login_events_user_time ON login_events(zitadel_user_id, occurred_at DESC);
CREATE INDEX idx_login_events_ip ON login_events(ip);

-- Composite PK encodes "same IP + same account" by construction: blocking is
-- never global-IP, so an attacker can't lock out the real owner's own IP
-- unless they're actually attacking from it.
CREATE TABLE ip_block_state (
    zitadel_user_id TEXT NOT NULL,
    ip TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    blocked_at TEXT,
    unblocked_at TEXT,
    unblocked_by TEXT,
    PRIMARY KEY (zitadel_user_id, ip)
);

-- Binaries (logo/background/favicon) live on disk under branding_asset_dir;
-- only the path is stored here, keeping the sqlite file small/backupable.
CREATE TABLE bridge_branding (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    title TEXT,
    logo_path TEXT,
    background_path TEXT,
    favicon_path TEXT,
    updated_at TEXT
);

CREATE TABLE idp_signing_keys (
    id INTEGER PRIMARY KEY,
    kid TEXT UNIQUE NOT NULL,
    private_key_pem TEXT NOT NULL,
    public_key_pem TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
