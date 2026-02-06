#!/usr/bin/env bash
set -euo pipefail

compose_file="docker-compose.yml"
project_name=""

usage() {
  cat <<'USAGE'
Usage: scripts/find_compose_network.sh [-f compose-file] [--project name]

Prints the docker network name used by a running compose stack so it can be
assigned to DESKTOP_COMPOSE_NETWORK.

Examples:
  scripts/find_compose_network.sh
  scripts/find_compose_network.sh -f docker-compose.yml
  scripts/find_compose_network.sh --project tradar
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)
      compose_file="$2"
      shift 2
      ;;
    --project)
      project_name="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -n "$project_name" ]]; then
  candidate="${project_name}_default"
  if docker network inspect "$candidate" >/dev/null 2>&1; then
    echo "$candidate"
    exit 0
  fi
  echo "Network not found: $candidate" >&2
  exit 2
fi

if [[ ! -f "$compose_file" ]]; then
  echo "Compose file not found: $compose_file" >&2
  exit 2
fi

container_ids="$(docker compose -f "$compose_file" ps -q || true)"
if [[ -z "$container_ids" ]]; then
  echo "No running containers found for $compose_file" >&2
  exit 3
fi

first_id="$(echo "$container_ids" | head -n 1)"
networks_json="$(docker inspect -f '{{json .NetworkSettings.Networks}}' "$first_id")"

python - <<'PY' "$networks_json"
import json
import sys

raw = sys.argv[1]
data = json.loads(raw) if raw else {}
names = list(data.keys())
if not names:
    print("No networks found", file=sys.stderr)
    sys.exit(4)
default = [n for n in names if n.endswith("_default")]
if default:
    print(default[0])
else:
    print(names[0])
PY
