#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT_DIR"

if docker compose version >/dev/null 2>&1; then
  exec docker compose "$@"
fi

if command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose "$@"
fi

if [ -x /opt/homebrew/bin/docker-compose ]; then
  exec /opt/homebrew/bin/docker-compose "$@"
fi

echo "Docker Compose is required (plugin or docker-compose executable)." >&2
exit 127
