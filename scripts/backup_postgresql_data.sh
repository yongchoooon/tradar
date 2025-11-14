#!/usr/bin/env bash
# Back up PostgreSQL and OpenSearch data directories into workspace.

set -euo pipefail

POSTGRES_SERVICE=${POSTGRES_SERVICE:-postgresql}
POSTGRES_DATA_SRC=${POSTGRES_DATA_SRC:-/var/lib/postgresql/14/main}
POSTGRES_BACKUP_BASE=${POSTGRES_BACKUP_BASE:-$HOME/workspace/postgres-data}
POSTGRES_BACKUP_DIR="${POSTGRES_BACKUP_BASE}/main"

mkdir -p "$POSTGRES_BACKUP_BASE"

info() { echo "[backup] $*"; }

info "Stopping PostgreSQL service: $POSTGRES_SERVICE"
sudo service "$POSTGRES_SERVICE" stop

info "Syncing PostgreSQL data from $POSTGRES_DATA_SRC -> $POSTGRES_BACKUP_DIR"
sudo rsync -a --delete "$POSTGRES_DATA_SRC/" "$POSTGRES_BACKUP_DIR/"

info "Restarting PostgreSQL service"
sudo service "$POSTGRES_SERVICE" start

info "Backup complete."
