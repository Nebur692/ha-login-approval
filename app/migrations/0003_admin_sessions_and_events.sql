-- Admin panel sign-in with sessions instead of HTTP Basic Auth, and a record
-- of what is done in it.

-- Only a hash of the session token is stored: a copy of this database is not
-- a way into the panel.
CREATE TABLE admin_sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    ip TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);

-- Every sign-in (good or bad) and every change made from the panel. Failed
-- sign-ins are also what the attempt limit counts, so they live in one place.
CREATE TABLE admin_events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX admin_events_at ON admin_events (at);
CREATE INDEX admin_events_failures ON admin_events (event, ip, at);
