#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT_DIR/backend"

if command -v uv >/dev/null 2>&1; then
  uv sync --frozen --all-extras
  uv run ruff format --check .
  uv run ruff check .
  uv run mypy src
  case "${TRAINLAB_DATABASE_URL:-}" in
    *_test*)
      uv run pytest
      exit 0
      ;;
  esac
fi

cd "$ROOT_DIR"
exec ./backend/scripts/compose.sh --profile test run --build --rm backend-test
