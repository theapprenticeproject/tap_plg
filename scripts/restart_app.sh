# SKIP_GIT_PULL=1 sh scripts/restart_app.sh

#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BRANCH="${BRANCH:-plg_integration}"
APP_SERVICE="${APP_SERVICE:-plg_app.service}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-plg_postgres.service}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

start_postgres_service_if_present() {
  if systemctl --user cat "$POSTGRES_SERVICE" >/dev/null 2>&1; then
    log "Ensuring PostgreSQL service is running"
    systemctl --user start "$POSTGRES_SERVICE"
  else
    log "PostgreSQL service $POSTGRES_SERVICE not found; migrations will start PostgreSQL if needed"
  fi
}

cd "$APP_DIR"

if [ "$SKIP_GIT_PULL" != "1" ]; then
  log "Pulling latest code for $BRANCH"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
else
  log "Skipping git pull because SKIP_GIT_PULL=$SKIP_GIT_PULL"
fi

start_postgres_service_if_present

log "Applying database migrations"
./scripts/run_db_migrations.sh

log "Restarting application service"
systemctl --user restart "$APP_SERVICE"
systemctl --user --no-pager --full status "$APP_SERVICE"

log "Restart complete"
