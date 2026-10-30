#!/bin/sh
set -eu

# Docker named volumes are created as root. NAS users often need a specific
# UID/GID to read bind-mounted shares; PUID/PGID let you align the container
# user with those ownership rules. Defaults match the image's app user.
if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"
    if [ "$PGID" != "1000" ] || [ "$PUID" != "1000" ]; then
        groupmod -o -g "$PGID" app 2>/dev/null || true
        usermod -o -u "$PUID" app 2>/dev/null || true
    fi
    mkdir -p "${UPLOAD_DIR:-/data/uploads}" "${TESSERA_CACHE_DIR:-/data/tessera}" "${TILES_DIR:-/data/tiles}"
    chown -R app:app "${UPLOAD_DIR:-/data/uploads}" "${TESSERA_CACHE_DIR:-/data/tessera}" "${TILES_DIR:-/data/tiles}" 2>/dev/null || true
    exec gosu app "$0" "$@"
fi

# Run idempotent migrations before the API or worker starts. This also waits
# for Postgres, which is useful on NAS devices that boot slowly.
python -m app.migrate

exec "$@"
