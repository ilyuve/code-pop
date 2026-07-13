#!/usr/bin/env bash
# CodePop DB migration: resize embeddings vector column to 1024 (BAAI/bge-m3).
# Reads DATABASE_URL from environment or .env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SQL_FILE="$PROJECT_ROOT/backend/migrations/001_bge_m3_1024.sql"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set. Export it or define it in .env" >&2
  exit 1
fi

if [[ ! -f "$SQL_FILE" ]]; then
  echo "ERROR: migration file not found: $SQL_FILE" >&2
  exit 1
fi

echo "Running migration: $SQL_FILE"
echo "Database: $DATABASE_URL"
echo ""

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SQL_FILE"

echo ""
echo "Migration completed successfully."
echo "Repositories have been reset to 'pending' status. Re-index them via the UI."
