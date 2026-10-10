-- v2.3.0: signing-key rotation. A rotated-out key stops signing at once but
-- stays in the JWKS until retired_at + the overlap window, so a token it
-- signed just before the rotation still verifies; then it is deleted.
ALTER TABLE idp_signing_keys ADD COLUMN retired_at TEXT;
