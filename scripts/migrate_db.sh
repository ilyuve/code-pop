#!/usr/bin/env bash
# CodePop DB migration runner.
# Reads DATABASE_URL from environment or .env and executes all SQL migrations
# under backend/migrations/ in lexical order.
# To run a specific migration, pass its filename as the first argument, e.g.:
#   ./scripts/migrate_db.sh 003_add_branch_columns.sql

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$PROJECT_ROOT/backend/migrations"

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

run_sql() {
  local file="$1"
  echo "Running migration: $file"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$file"
}

if [[ "${1:-}" ]]; then
  SQL_FILE="$MIGRATIONS_DIR/$1"
  if [[ ! -f "$SQL_FILE" ]]; then
    echo "ERROR: migration file not found: $SQL_FILE" >&2
    exit 1
  fi
  run_sql "$SQL_FILE"
else
  # Default: run the latest migration file only. Earlier migrations (e.g. 001)
  # may be destructive (TRUNCATE), so running all of them by default is unsafe.
  shopt -s nullglob
  files=("$MIGRATIONS_DIR"/*.sql)
  if [[ ${#files[@]} -eq 0 ]]; then
    echo "ERROR: no migration files found in $MIGRATIONS_DIR" >&2
    exit 1
  fi
  # Sort and pick the last one
  IFS=$'\n' sorted_files=("$(printf '%s\n' "${files[@]}" | sort)"); unset IFS
  latest="${sorted_files[*]: -1}"
  run_sql "$latest"
fi

echo ""
echo "Migration(s) completed successfully."
