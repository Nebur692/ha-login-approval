#!/bin/sh
# Runs the service as an unprivileged user (v2.3.0).
#
# Started as root — the default, and what every install before v2.3.0 did —
# it first hands /data over to PUID:PGID, which also migrates a data folder
# created by an older version, then drops root for good. Started with
# `--user` instead, it is already unprivileged and just runs.
#
# Only the database is made private (0600, done in app/db.py too): it holds
# the id_token signing key. The GeoIP databases and branding images are
# public data and stay readable, since other containers may mount them.
set -eu

if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"
    if [ "$PUID" = "0" ]; then
        echo "PUID=0 would run the service as root; refusing. Use any other user ID." >&2
        exit 1
    fi
    chown -R "$PUID:$PGID" /data
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --no-new-privs -- "$@"
fi

exec "$@"
