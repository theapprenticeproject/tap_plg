#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-$(id -un)}"
APP_HOME="${APP_HOME:-$HOME}"
APP_DIR="${APP_DIR:-$APP_HOME/tap_plg}"
REPO_URL="${REPO_URL:-https://github.com/theapprenticeproject/tap_plg.git}"
BRANCH="${BRANCH:-plg_integration}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-plg_postgres.service}"
APP_SERVICE="${APP_SERVICE:-plg_app.service}"
DOWNLOAD_CLIP_MODEL="${DOWNLOAD_CLIP_MODEL:-1}"
ENV_FILE="${ENV_FILE:-}"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

clone_or_update_repo() {
  if [ -d "$APP_DIR/.git" ]; then
    log "Updating existing repository in $APP_DIR"
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
  else
    log "Cloning $REPO_URL into $APP_DIR"
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
}

install_env_file() {
  cd "$APP_DIR"

  if [ -f ".env" ]; then
    log ".env already exists"
    return
  fi

  if [ -n "$ENV_FILE" ]; then
    if [ ! -f "$ENV_FILE" ]; then
      echo "ERROR: ENV_FILE does not exist: $ENV_FILE" >&2
      exit 1
    fi

    log "Creating .env from $ENV_FILE"
    cp "$ENV_FILE" .env
    return
  fi

  echo "ERROR: .env is required in $APP_DIR, or pass ENV_FILE=/path/to/envfile when running this script." >&2
  exit 1
}

setup_python_environment() {
  cd "$APP_DIR"

  log "Creating/updating Python virtual environment"
  "$PYTHON_BIN" -m venv venv
  ./venv/bin/python -m pip install podman-compose

  log "Starting production environment"
  ./start-prod-env.sh --with-api

  if [ "$DOWNLOAD_CLIP_MODEL" = "1" ]; then
    log "Downloading CLIP model if it is not already present"
    ./venv/bin/python scripts/download_clip_model.py --model ViT-L-14
  else
    log "Skipping CLIP model download because DOWNLOAD_CLIP_MODEL=$DOWNLOAD_CLIP_MODEL"
  fi
}

install_system_packages() {
  log "Installing OS packages"
  run_sudo apt update
  run_sudo apt install -y podman vim git python3.10-venv

  log "Configuring systemd delegation for rootless Podman"
  run_sudo mkdir -p /etc/systemd/system/user@.service.d
  run_sudo tee /etc/systemd/system/user@.service.d/delegate.conf >/dev/null <<'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
  run_sudo systemctl daemon-reload
}

install_user_services() {
  cd "$APP_DIR"

  local systemd_dir="$HOME/.config/systemd/user"
  mkdir -p "$systemd_dir"

  log "Writing user systemd services"
  cat >"$systemd_dir/$POSTGRES_SERVICE" <<EOF
[Unit]
Description=PLG PostgreSQL database
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/podman-compose -f docker-postgres.yml up -d
ExecStop=$APP_DIR/venv/bin/podman-compose -f docker-postgres.yml down
TimeoutStartSec=180

[Install]
WantedBy=default.target
EOF

  cat >"$systemd_dir/$APP_SERVICE" <<EOF
[Unit]
Description=Plagiarism App
Requires=$POSTGRES_SERVICE
After=$POSTGRES_SERVICE network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

  log "Enabling linger for $APP_USER"
  run_sudo loginctl enable-linger "$APP_USER"

  systemctl --user daemon-reload
  systemctl --user enable --now "$POSTGRES_SERVICE"
}

run_migrations() {
  cd "$APP_DIR"
  log "Applying database initialization and migrations"
  ./scripts/run_db_migrations.sh
}

start_app_service() {
  log "Starting application service"
  systemctl --user enable --now "$APP_SERVICE"
  systemctl --user restart "$APP_SERVICE"
}

main() {
  install_system_packages
  clone_or_update_repo
  install_env_file
  setup_python_environment
  install_user_services
  run_migrations
  start_app_service

  log "Setup complete"
  echo "Status:  systemctl --user status $APP_SERVICE"
  echo "Logs:    journalctl --user -u $APP_SERVICE -f -n 100 --no-pager"
}

main "$@"
