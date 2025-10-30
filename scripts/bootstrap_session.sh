#!/usr/bin/env bash
# Resume script for KT Cloud sessions with existing data.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENSEARCH_URL="${OPENSEARCH_URL:-http://localhost:9200}"
DEFAULT_OPENSEARCH_DIR="${HOME}/opensearch-2.12.0"
OPENSEARCH_DIR="${OPENSEARCH_DIR:-${DEFAULT_OPENSEARCH_DIR}}"
OPENSEARCH_ARCHIVE="${OPENSEARCH_ARCHIVE:-https://artifacts.opensearch.org/releases/bundle/opensearch/2.12.0/opensearch-2.12.0-linux-x64.tar.gz}"

if [ -d "${OPENSEARCH_DIR}/nodes" ] && [ ! -d "${OPENSEARCH_DIR}/bin" ]; then
  if [ -z "${OPENSEARCH_DATA_DIR:-}" ]; then
    OPENSEARCH_DATA_DIR="${OPENSEARCH_DIR}"
  fi
  echo "[resume] Detected OPENSEARCH_DIR pointing to data directory; using ${DEFAULT_OPENSEARCH_DIR} for binaries" >&2
  OPENSEARCH_DIR="${DEFAULT_OPENSEARCH_DIR}"
fi

if [ -z "${OPENSEARCH_DATA_DIR:-}" ]; then
  if [ -d "${HOME}/workspace/opensearch-data" ]; then
    OPENSEARCH_DATA_DIR="${HOME}/workspace/opensearch-data"
  else
    OPENSEARCH_DATA_DIR="${OPENSEARCH_DIR}/data"
  fi
fi

DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/tradar}"
export DATABASE_URL
export OPENSEARCH_URL
export OPENSEARCH_DATA_DIR
export OPENSEARCH_INDEX="${OPENSEARCH_INDEX:-tradar_trademarks}"
export OPENSEARCH_SEARCH_FIELDS="${OPENSEARCH_SEARCH_FIELDS:-title_korean^2,title_english,aliases^0.5}"

install_python_requirements() {
  if [ -f "${REPO_ROOT}/requirements.txt" ]; then
    echo "[resume] Installing Python requirements"
    pip install -r "${REPO_ROOT}/requirements.txt"
  fi
}

ensure_python_dependencies() {
  local required
  required=$(python - <<'PY'
from importlib import util
from importlib.metadata import PackageNotFoundError, version

requirements = {
    "opensearchpy": ("opensearch-py", "opensearch-py==2.4.*", ("2", "4")),
    "psycopg": ("psycopg", "psycopg[binary]==3.2.*", ("3", "2")),
}

def version_prefix_matches(installed: str, expected_prefix: tuple[str, ...]) -> bool:
    parts = installed.split(".")
    if len(parts) < len(expected_prefix):
        return False
    return tuple(parts[: len(expected_prefix)]) == expected_prefix

to_install: list[str] = []
for module, (package, spec, expected_prefix) in requirements.items():
    if util.find_spec(module) is None:
        to_install.append(spec)
        continue

    try:
        installed_version = version(package)
    except PackageNotFoundError:
        to_install.append(spec)
        continue

    if not version_prefix_matches(installed_version, expected_prefix):
        to_install.append(spec)

print(" ".join(dict.fromkeys(to_install)))
PY
  )

  if [ -n "${required}" ]; then
    echo "[resume] Installing Python packages: ${required}"
    pip install --user ${required}
  fi
}

ensure_postgresql_packages() {
  if ! command -v sudo >/dev/null 2>&1; then
    echo "[resume] sudo command not found; unable to auto-install PostgreSQL." >&2
    return 1
  fi

  local need_install=false
  if ! command -v psql >/dev/null 2>&1; then
    need_install=true
  else
    local status_output
    status_output=$(sudo service postgresql status 2>&1 || true)
    if echo "${status_output}" | grep -qi "unrecognized service"; then
      need_install=true
    fi
  fi

  if [ "${need_install}" = true ]; then
    echo "[resume] Installing PostgreSQL base packages"
    sudo apt-get update -y
    sudo apt-get install -y postgresql postgresql-contrib
  fi

  return 0
}

ensure_pgvector_extension() {
  local pgversion
  pgversion=$(psql --version | awk '{print $3}' | cut -d. -f1)
  if sudo -u postgres psql -tAc "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'" | grep -q 1; then
    return 0
  fi

  echo "[resume] Installing pgvector extension package"
  if sudo apt-get install -y "postgresql-${pgversion}-pgvector"; then
    return 0
  fi

  echo "[resume] pgvector package not available; building from source"
  sudo apt-get install -y build-essential git "postgresql-server-dev-${pgversion}"
  local tmp_dir
  tmp_dir=$(mktemp -d)
  (cd "${tmp_dir}" && git clone https://github.com/pgvector/pgvector.git >/dev/null 2>&1)
  (cd "${tmp_dir}/pgvector" && make >/dev/null 2>&1 && sudo make install >/dev/null 2>&1)
  rm -rf "${tmp_dir}"
}

ensure_database_credentials() {
  if ! command -v sudo >/dev/null 2>&1; then
    return 0
  fi

  local sql
  sql=$(python - <<'PY'
import os
from urllib.parse import urlparse, unquote

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit

parsed = urlparse(url)
if parsed.scheme not in {"postgresql", "postgres"}:
    raise SystemExit

username = parsed.username
password = parsed.password
if not username or password is None:
    raise SystemExit

username = unquote(username)
password = unquote(password)
escaped_password = password.replace("'", "''")

print(f"ALTER USER \"{username}\" WITH PASSWORD '{escaped_password}';")
PY
  ) || return 0

  if [ -z "${sql}" ]; then
    return 0
  fi

  sudo -u postgres psql -c "${sql}" >/dev/null
}

restore_postgres_snapshot_if_needed() {
  local snapshot_dir="${POSTGRES_SNAPSHOT_DIR:-${HOME}/workspace/postgres-data}"
  if [ ! -d "${snapshot_dir}" ]; then
    return 0
  fi

  if ! sudo test -f "${snapshot_dir}/PG_VERSION"; then
    echo "[resume] PostgreSQL snapshot at ${snapshot_dir} is missing PG_VERSION; skipping restore" >&2
    return 0
  fi

  local cluster_info
  cluster_info=$(sudo pg_lsclusters --no-header 2>/dev/null | head -n1 || true)
  if [ -z "${cluster_info}" ]; then
    echo "[resume] Unable to determine PostgreSQL data directory" >&2
    return 0
  fi

  local version cluster port status owner data_dir log_file
  read -r version cluster port status owner data_dir log_file <<<"${cluster_info}"
  if [ -z "${data_dir}" ]; then
    return 0
  fi

  local snapshot_version
  snapshot_version=$(sudo cat "${snapshot_dir}/PG_VERSION" | tr -d '\n\r\t ')
  if [ "${snapshot_version%%.*}" != "${version%%.*}" ]; then
    echo "[resume] Snapshot version ${snapshot_version} does not match cluster ${version}; skipping restore" >&2
    return 0
  fi

  local db_exists
  db_exists=$(sudo -u postgres psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='tradar'" 2>/dev/null || true)
  local table_exists="f"
  if [ "${db_exists}" = "1" ]; then
    table_exists=$(sudo -u postgres psql -d tradar -tAc "SELECT to_regclass('public.trademarks') IS NOT NULL" 2>/dev/null || true)
  fi

  if [ "${table_exists}" = "t" ]; then
    return 0
  fi

  echo "[resume] Restoring PostgreSQL data directory from ${snapshot_dir}"
  sudo service postgresql stop
  sudo rm -rf "${data_dir}"
  sudo mkdir -p "${data_dir}"
  sudo cp -a "${snapshot_dir}/." "${data_dir}"
  sudo chown -R postgres:postgres "${data_dir}"
  sudo chmod 700 "${data_dir}"
  sudo service postgresql start

  # Ensure table check is refreshed for callers after restore.
  return 0
}

ensure_opensearch_install() {
  if [ -x "${OPENSEARCH_DIR}/bin/opensearch" ]; then
    return 0
  fi

  if [ -d "${OPENSEARCH_DIR}" ]; then
    echo "[resume] Existing OpenSearch directory at ${OPENSEARCH_DIR} is missing executables" >&2
  fi

  echo "[resume] Installing OpenSearch into ${OPENSEARCH_DIR}"
  local parent_dir
  parent_dir=$(dirname "${OPENSEARCH_DIR}")
  mkdir -p "${parent_dir}"

  local tmp_dir
  tmp_dir=$(mktemp -d)
  curl -fsSL "${OPENSEARCH_ARCHIVE}" -o "${tmp_dir}/opensearch.tar.gz"
  tar -xzf "${tmp_dir}/opensearch.tar.gz" -C "${tmp_dir}"
  local extracted
  extracted=$(find "${tmp_dir}" -maxdepth 1 -type d -name 'opensearch-*' | head -n1)
  if [ -z "${extracted}" ]; then
    echo "[resume] Failed to extract OpenSearch archive" >&2
    rm -rf "${tmp_dir}"
    return 1
  fi

  rm -rf "${OPENSEARCH_DIR}"
  mv "${extracted}" "${OPENSEARCH_DIR}"
  rm -rf "${tmp_dir}"

  configure_opensearch_config
}

configure_opensearch_config() {
  local config_file="${OPENSEARCH_DIR}/config/opensearch.yml"
  mkdir -p "$(dirname "${config_file}")"
  touch "${config_file}"

  if ! grep -q '^plugins\.security\.disabled:' "${config_file}"; then
    echo 'plugins.security.disabled: true' >> "${config_file}"
  fi

  if [ -n "${OPENSEARCH_DATA_DIR}" ] && [ "${OPENSEARCH_DATA_DIR}" != "${OPENSEARCH_DIR}/data" ]; then
    mkdir -p "${OPENSEARCH_DATA_DIR}"
    if grep -q '^path\.data:' "${config_file}"; then
      sed -i "s|^path\.data:.*|path.data: ${OPENSEARCH_DATA_DIR}|" "${config_file}"
    else
      echo "path.data: ${OPENSEARCH_DATA_DIR}" >> "${config_file}"
    fi
  fi
}

echo "[resume] Adjusting resource limits"
ulimit -n 65536 || true
ulimit -l unlimited || true

echo "[resume] Ensuring PostgreSQL is available"
if ensure_postgresql_packages; then
  if sudo service postgresql status >/dev/null 2>&1; then
    echo "[resume] PostgreSQL already running"
  else
    echo "[resume] Starting PostgreSQL service"
    if ! sudo service postgresql start >/dev/null 2>&1; then
      echo "[resume] Failed to start PostgreSQL service" >&2
      exit 1
    fi
  fi

  restore_postgres_snapshot_if_needed
  ensure_database_credentials

  if sudo -u postgres psql -tAc "SELECT 1" >/dev/null 2>&1; then
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='tradar'" | grep -q 1; then
      echo "[resume] Creating tradar database"
      sudo -u postgres createdb tradar
    fi

    if ensure_pgvector_extension; then
      echo "[resume] Ensuring pgvector extension is enabled"
      sudo -u postgres psql -d tradar -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
    else
      echo "[resume] Warning: pgvector extension could not be installed automatically" >&2
    fi
  fi
else
  echo "[resume] Skipping PostgreSQL provisioning; please install manually." >&2
fi

echo "[resume] Ensuring OpenSearch is running"
if ! ensure_opensearch_install; then
  echo "[resume] Unable to prepare OpenSearch installation" >&2
  exit 1
fi
configure_opensearch_config
if ! curl -fsSL "${OPENSEARCH_URL}/_cluster/health" >/dev/null 2>&1; then
  if [ ! -d "${OPENSEARCH_DIR}" ]; then
    echo "[resume] OpenSearch install not found at ${OPENSEARCH_DIR}" >&2
    exit 1
  fi
  nohup "${OPENSEARCH_DIR}/bin/opensearch" > "${HOME}/opensearch-console.log" 2>&1 &
  for attempt in $(seq 1 60); do
    if curl -fsSL "${OPENSEARCH_URL}/_cluster/health" >/dev/null 2>&1; then
      echo "[resume] OpenSearch is healthy"
      break
    fi
    sleep 2
    if [ "${attempt}" -eq 60 ]; then
      echo "[resume] OpenSearch did not become healthy in time" >&2
      exit 1
    fi
  done
else
  echo "[resume] OpenSearch already running"
fi

echo "[resume] Syncing OpenSearch index"
cd "${REPO_ROOT}"
install_python_requirements
ensure_python_dependencies
bash scripts/sync_opensearch.sh

echo "[resume] Session services ready"
