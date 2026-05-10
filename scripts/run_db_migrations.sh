#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-postgres.yml}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-plg-postgresdb}"
INIT_SQL="${INIT_SQL:-database/init.sql}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-database/migrations}"
BASELINE_EXISTING_MIGRATIONS="${BASELINE_EXISTING_MIGRATIONS:-0}"
INIT_CHECK_SQL="${INIT_CHECK_SQL:-SELECT to_regclass('public.submissions') IS NOT NULL;}"

cd "$APP_DIR"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
else
  echo "ERROR: .env is required in $APP_DIR" >&2
  exit 1
fi

: "${POSTGRES_DB:?POSTGRES_DB must be set in .env}"
: "${POSTGRES_USER:?POSTGRES_USER must be set in .env}"

if command -v podman >/dev/null 2>&1; then
  CONTAINER_CMD="${CONTAINER_CMD:-podman}"
elif command -v docker >/dev/null 2>&1; then
  CONTAINER_CMD="${CONTAINER_CMD:-docker}"
else
  echo "ERROR: podman or docker is required" >&2
  exit 1
fi

if [ -x "$APP_DIR/venv/bin/podman-compose" ]; then
  COMPOSE_CMD="${COMPOSE_CMD:-$APP_DIR/venv/bin/podman-compose}"
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE_CMD="${COMPOSE_CMD:-podman-compose}"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="${COMPOSE_CMD:-docker-compose}"
elif docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
else
  COMPOSE_CMD=""
fi

find_postgres_container() {
  if "$CONTAINER_CMD" container exists "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
    echo "$POSTGRES_CONTAINER"
    return
  fi

  for candidate in plg-postgresdb plg-postgres; do
    if "$CONTAINER_CMD" container exists "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done

  echo "$POSTGRES_CONTAINER"
}

start_postgres_if_needed() {
  if [ -n "$COMPOSE_CMD" ] && [ -f "$COMPOSE_FILE" ]; then
    $COMPOSE_CMD -f "$COMPOSE_FILE" up -d postgres
  else
    "$CONTAINER_CMD" start "$(find_postgres_container)" >/dev/null
  fi
}

wait_for_postgres() {
  local container="$1"
  local attempt=1

  while [ "$attempt" -le 60 ]; do
    if "$CONTAINER_CMD" exec "$container" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  echo "ERROR: PostgreSQL did not become ready in time" >&2
  exit 1
}

psql_exec() {
  local container="$1"
  shift
  "$CONTAINER_CMD" exec "$container" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

psql_file() {
  local container="$1"
  local file="$2"
  "$CONTAINER_CMD" exec -i "$container" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <"$file"
}

record_migration() {
  local container="$1"
  local migration_name="$2"

  psql_exec "$container" -c "INSERT INTO schema_migrations (migration_name) VALUES ('$migration_name') ON CONFLICT (migration_name) DO NOTHING;"
}

main() {
  start_postgres_if_needed

  local container
  container="$(find_postgres_container)"

  wait_for_postgres "$container"

  local initialized_from_init=0
  local init_check_result
  init_check_result="$(
    psql_exec "$container" -tAc "$INIT_CHECK_SQL"
  )"

  if [ "$init_check_result" != "t" ] && [ -f "$INIT_SQL" ]; then
    echo "Applying $INIT_SQL"
    psql_file "$container" "$INIT_SQL"
    initialized_from_init=1
  fi

  psql_exec "$container" -c "
CREATE TABLE IF NOT EXISTS schema_migrations (
  id SERIAL PRIMARY KEY,
  migration_name VARCHAR(255) UNIQUE NOT NULL,
  applied_at TIMESTAMP DEFAULT NOW()
);"

  if [ -d "$MIGRATIONS_DIR" ]; then
    for migration_file in "$MIGRATIONS_DIR"/*.sql; do
      [ -f "$migration_file" ] || continue

      migration_name="$(basename "$migration_file")"

      if [ "$initialized_from_init" = "1" ]; then
        echo "Recording migration already included by $INIT_SQL: $migration_name"
        record_migration "$container" "$migration_name"
        continue
      fi

      if [ "$BASELINE_EXISTING_MIGRATIONS" = "1" ]; then
        echo "Recording existing migration without applying: $migration_name"
        record_migration "$container" "$migration_name"
        continue
      fi

      already_applied="$(
        psql_exec "$container" -tAc "SELECT COUNT(*) FROM schema_migrations WHERE migration_name = '$migration_name';"
      )"

      if [ "$already_applied" = "0" ]; then
        echo "Applying migration: $migration_name"
        psql_file "$container" "$migration_file"
        record_migration "$container" "$migration_name"
      else
        echo "Skipping already-applied migration: $migration_name"
      fi
    done
  fi
}

main "$@"
