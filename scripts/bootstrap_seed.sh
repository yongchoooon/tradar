#!/usr/bin/env bash
# Full bootstrap script for fresh KT Cloud sessions.
# Installs system deps, seeds PostgreSQL/pgvector, and populates OpenSearch.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/tradar}"
METADATA_PATH="${1:-${REPO_ROOT}/data/trademarks.json}"
IMAGES_ROOT="${2:-${REPO_ROOT}/data/images}"
IMAGE_BACKEND="${BOOTSTRAP_IMAGE_BACKEND:-${EMBED_BACKEND:-torch}}"
TEXT_BACKEND="${BOOTSTRAP_TEXT_BACKEND:-${EMBED_BACKEND:-torch}}"
METACLIP_MODEL="${BOOTSTRAP_METACLIP_MODEL:-${METACLIP_MODEL_NAME:-}}"
DINOV2_MODEL="${BOOTSTRAP_DINOV2_MODEL:-${DINOV2_MODEL_NAME:-}}"
EMBED_DEVICE="${BOOTSTRAP_EMBED_DEVICE:-${EMBED_DEVICE:-}}"
OPENSEARCH_URL="${BOOTSTRAP_OPENSEARCH_URL:-http://localhost:9200}"
OPENSEARCH_ARCHIVE="${BOOTSTRAP_OPENSEARCH_ARCHIVE:-https://artifacts.opensearch.org/releases/bundle/opensearch/2.12.0/opensearch-2.12.0-linux-x64.tar.gz}"
OPENSEARCH_DIR="${BOOTSTRAP_OPENSEARCH_DIR:-${HOME}/opensearch-2.12.0}"
LLM_API_KEY="${BOOTSTRAP_LLM_API_KEY:-${OPENAI_API_KEY:-}}"

echo "[bootstrap-seed] Using metadata: ${METADATA_PATH}"
echo "[bootstrap-seed] Using images root: ${IMAGES_ROOT}"
echo "[bootstrap-seed] Database URL: ${DB_URL}"

if ! command -v sudo >/dev/null 2>&1; then
  echo "[bootstrap-seed] sudo command not found. Please install PostgreSQL manually." >&2
  exit 1
fi

echo "[bootstrap-seed] Updating apt repositories…"
sudo apt-get update -y

echo "[bootstrap-seed] Installing PostgreSQL core packages…"
sudo apt-get install -y postgresql postgresql-contrib || {
  echo "[bootstrap-seed] Failed to install core PostgreSQL packages." >&2
  exit 1
}

PG_VERSION=$(psql --version | awk '{print $3}' | cut -d. -f1)
PG_DEV_PKG="postgresql-server-dev-${PG_VERSION}"

echo "[bootstrap-seed] Attempting to install pgvector package…"
if ! sudo apt-get install -y "postgresql-${PG_VERSION}-pgvector"; then
  echo "[bootstrap-seed] pgvector package not available, building from source…"
  sudo apt-get install -y build-essential git "${PG_DEV_PKG}"
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf ${TMP_DIR}' EXIT
  (cd "${TMP_DIR}" && git clone https://github.com/pgvector/pgvector.git)
  (cd "${TMP_DIR}/pgvector" && make && sudo make install)
fi

echo "[bootstrap-seed] Starting PostgreSQL service…"
sudo service postgresql start

echo "[bootstrap-seed] Configuring database user/database…"
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='tradar'" | grep -q 1; then
  sudo -u postgres createdb tradar
fi

echo "[bootstrap-seed] Enabling pgvector extension…"
sudo -u postgres psql -d tradar -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "[bootstrap-seed] Installing Python dependencies…"
echo "[bootstrap-seed] Removing conflicting CUDA-specific packages if present…"
pip uninstall -y transformer-engine flash-attn >/dev/null 2>&1 || true
pip uninstall -y transformers >/dev/null 2>&1 || true
pip install -r "${REPO_ROOT}/requirements.txt"

echo "[bootstrap-seed] Configuring ulimit for OpenSearch"
ulimit -n 65536 || true
ulimit -l unlimited || true

echo "[bootstrap-seed] Ensuring OpenSearch is running at ${OPENSEARCH_URL}"
if ! curl -fsSL "${OPENSEARCH_URL}" >/dev/null 2>&1; then
  echo "[bootstrap-seed] OpenSearch not reachable, installing local bundle"
  mkdir -p "${HOME}"
  cd "${HOME}"
  if [ ! -d "${OPENSEARCH_DIR}" ]; then
    curl -L "${OPENSEARCH_ARCHIVE}" -o opensearch.tar.gz
    tar -xzf opensearch.tar.gz
    rm opensearch.tar.gz
    echo 'plugins.security.disabled: true' >> "${OPENSEARCH_DIR}/config/opensearch.yml"
  fi
  nohup "${OPENSEARCH_DIR}/bin/opensearch" >/dev/null 2>&1 &
  cd "${REPO_ROOT}"
else
  echo "[bootstrap-seed] OpenSearch already reachable"
fi

echo "[bootstrap-seed] Waiting for OpenSearch health"
for attempt in $(seq 1 60); do
  if curl -fsSL "${OPENSEARCH_URL}/_cluster/health" >/dev/null 2>&1; then
    echo "[bootstrap-seed] OpenSearch is healthy"
    break
  fi
  sleep 2
  if [ "${attempt}" -eq 60 ]; then
    echo "[bootstrap-seed] OpenSearch did not become healthy in time" >&2
    exit 1
  fi
done

if [ -n "${LLM_API_KEY}" ]; then
  cat > "${REPO_ROOT}/.env" <<EOF
OPENAI_API_KEY=${LLM_API_KEY}
TRADEMARK_LLM_ENABLED=true
TRADEMARK_LLM_MODEL=${BOOTSTRAP_LLM_MODEL:-gpt-4o-mini}
TRADEMARK_LLM_REASONING=${BOOTSTRAP_LLM_REASONING:-medium}
EOF
  echo "[bootstrap-seed] Wrote .env with LLM credentials"
fi

if [ -f "${METADATA_PATH}" ]; then
  echo "[bootstrap-seed] Running vector DB seeding script…"
  args=()
  if [ -n "${IMAGE_BACKEND}" ]; then
    args+=(--image-backend "${IMAGE_BACKEND}")
  fi
  if [ -n "${TEXT_BACKEND}" ]; then
    args+=(--text-backend "${TEXT_BACKEND}")
  fi
  if [ -n "${METACLIP_MODEL}" ]; then
    args+=(--metaclip-model "${METACLIP_MODEL}")
  fi
  if [ -n "${DINOV2_MODEL}" ]; then
    args+=(--dinov2-model "${DINOV2_MODEL}")
  fi
  if [ -n "${EMBED_DEVICE}" ]; then
    args+=(--embed-device "${EMBED_DEVICE}")
  fi
  if [ "${#args[@]}" -gt 0 ]; then
    python "${REPO_ROOT}/scripts/vector_db_prepare.py" \
      --metadata "${METADATA_PATH}" \
      --images-root "${IMAGES_ROOT}" \
      --database-url "${DB_URL}" \
      --truncate \
      "${args[@]}"
  else
    python "${REPO_ROOT}/scripts/vector_db_prepare.py" \
      --metadata "${METADATA_PATH}" \
      --images-root "${IMAGES_ROOT}" \
      --database-url "${DB_URL}" \
      --truncate
  fi
else
  echo "[bootstrap-seed] Metadata file not found at ${METADATA_PATH}; skipping seeding."
fi

export OPENSEARCH_URL
export OPENSEARCH_INDEX="${BOOTSTRAP_OPENSEARCH_INDEX:-tradar_trademarks}"
export OPENSEARCH_SEARCH_FIELDS="${BOOTSTRAP_OPENSEARCH_FIELDS:-title_korean^2,title_english,aliases^0.5}"

echo "[bootstrap-seed] Syncing OpenSearch index"
bash "${REPO_ROOT}/scripts/sync_opensearch.sh"

echo "[bootstrap-seed] Done."
