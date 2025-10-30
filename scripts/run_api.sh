#!/usr/bin/env bash
# Helper script to run the FastAPI service with all required environment variables.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env if present so user-defined variables override defaults
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "${REPO_ROOT}/.env"
  set +a
fi

# Allow overrides from the current shell; fall back to project defaults.
: "${DATABASE_URL:=postgresql://postgres:postgres@localhost:5432/tradar}"
: "${IMAGE_EMBED_BACKEND:=torch}"
: "${TEXT_EMBED_BACKEND:=torch}"
: "${METACLIP_MODEL_NAME:=/home/work/workspace/models/metaclip}"
: "${DINOV2_MODEL_NAME:=/home/work/workspace/models/dinov2}"
: "${EMBED_DEVICE:=cuda:0}"
: "${OPENSEARCH_URL:=http://localhost:9200}"
: "${OPENSEARCH_INDEX:=tradar_trademarks}"
: "${OPENSEARCH_SEARCH_FIELDS:=title_korean^2,title_english,aliases^0.5}"
: "${TRADEMARK_LLM_ENABLED:=true}"
: "${TRADEMARK_LLM_API_KEY:=${OPENAI_API_KEY:-}}"
: "${TRADEMARK_LLM_MODEL:=gpt-4o-mini}"
: "${TRADEMARK_LLM_REASONING:=medium}"
: "${MEDIA_ALLOWED_ROOTS:=/home/work/workspace/tradar-data:/home/work/workspace/tradar}"

export DATABASE_URL
export IMAGE_EMBED_BACKEND
export TEXT_EMBED_BACKEND
export METACLIP_MODEL_NAME
export DINOV2_MODEL_NAME
export EMBED_DEVICE
export OPENSEARCH_URL
export OPENSEARCH_INDEX
export OPENSEARCH_SEARCH_FIELDS
export TRADEMARK_LLM_ENABLED
export TRADEMARK_LLM_API_KEY
export TRADEMARK_LLM_MODEL
export TRADEMARK_LLM_REASONING
export MEDIA_ALLOWED_ROOTS

if [ -n "${TRADEMARK_LLM_API_KEY}" ]; then
  export OPENAI_API_KEY="${TRADEMARK_LLM_API_KEY}"
fi

uvicorn app.main:app --reload "$@"
