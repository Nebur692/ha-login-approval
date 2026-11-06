-- The map attached to each sign-in notification, kept for the audit log. One
-- per login request; the public copy the phone downloads is only ever in
-- memory and gone once the request has an answer.
CREATE TABLE login_maps (
    request_id TEXT PRIMARY KEY,
    png BLOB NOT NULL,
    created_at TEXT NOT NULL
);

-- Nothing deletes audit rows today, but a map must never outlive its last
-- one, whoever deletes them.
CREATE TRIGGER login_maps_follow_events AFTER DELETE ON login_events
WHEN NOT EXISTS (SELECT 1 FROM login_events WHERE request_id = OLD.request_id)
BEGIN
    DELETE FROM login_maps WHERE request_id = OLD.request_id;
END;

-- Network operator logos, one per ASN. png is NULL when none could be found,
-- so a missing one is not looked up again on every sign-in.
CREATE TABLE operator_logos (
    asn INTEGER PRIMARY KEY,
    png BLOB,
    fetched_at TEXT NOT NULL
);
