# tap_plg — Server Setup Guide

This document covers deploying `tap_plg` (the plagiarism detection service)
on a fresh Ubuntu server. Unlike tap_lms and rag_service, tap_plg is **not a
Frappe app** — it's a standalone Python service running two processes
(worker + API) managed via **Podman containers** and **systemd user services**.

---

## Overview

tap_plg runs as two containers managed by systemd:

| Container | Purpose | Managed by |
|---|---|---|
| `plg-postgres` | pgvector PostgreSQL database | `plg_postgres.service` |
| `plg-checker` | RabbitMQ consumer + plagiarism worker | `plg_app.service` |
| `plg-api` | FastAPI HTTP API | `plg_app.service` (via docker-compose) |

No nginx, no bench, no Frappe — just Python, Podman, and systemd.

---

## Prerequisites

- Ubuntu 22.04 VM (GCP or equivalent)
- A non-root user (e.g. `plg-dev`)
- SSH access
- GCP service account JSON file for GCS access
- `.env` file with production values (see Section 3)
- CLIP model downloaded or accessible (large file — ~3.5GB)

---

## 1. Install System Dependencies

These need to be installed on the host VM before running `setup_vm.sh`.
The setup script only installs `podman vim git python3.10-venv` — install
the rest manually first:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    podman \
    git \
    vim \
    nano \
    curl \
    wget \
    python3 \
    python3-pip \
    python3.10-venv \
    python3-dev \
    build-essential
```

> **Note:** `python3.10-venv` is required specifically — the setup script
> calls `python3 -m venv venv` which fails without it.

### Configure systemd delegation for rootless Podman

Required so Podman containers can use cgroups without root. First check if
it's already configured:

```bash
systemctl show user@$(id -u).service | grep Delegate
```

If it shows `Delegate=yes` — you're good, skip this step.

If it shows `Delegate=no`, configure it manually:

```bash
sudo mkdir -p /etc/systemd/system/user@.service.d
sudo tee /etc/systemd/system/user@.service.d/delegate.conf > /dev/null << 'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
sudo systemctl daemon-reload
```

> GCP Ubuntu VMs typically have this pre-configured. Desktop Linux and older
> server installs may not.

### Enable linger for the plg-dev user

Required so systemd user services start on boot without the user logging in:

```bash
sudo loginctl enable-linger plg-dev
```

---

## 2. Automated Setup (Recommended)

tap_plg ships with `scripts/setup_vm.sh` which handles everything in one
command. Clone the repo and run it:

```bash
# clone the repo
git clone --branch <branch> https://github.com/<org>/tap_plg.git ~/tap_plg
cd ~/tap_plg

# run setup with your .env file
ENV_FILE=/path/to/plg.env bash scripts/setup_vm.sh
```

The script will:
1. Install system packages (podman, git, python3-venv)
2. Configure systemd delegation for rootless Podman
3. Copy your `.env` file into place
4. Create a Python venv and install `podman-compose`
5. Start the production containers (`docker-compose-prod.yml`)
6. Download the CLIP model if not already present
7. Install and enable systemd user services
8. Run DB initialisation and migrations
9. Start the app

After it completes, check status:

```bash
systemctl --user status plg_postgres.service
systemctl --user status plg_app.service
journalctl --user -u plg_app.service -f -n 100
```

---

## 3. Manual Setup (Step by Step)

If you prefer to run each step manually or the automated script fails.
Assumes Section 1 (system dependencies) is already done.

### Set up Python venv

```bash
cd ~/tap_plg
python3 -m venv venv
./venv/bin/python -m pip install podman-compose
```

### Create .env file

```bash
# copy example and fill in production values
cp .env.example .env
nano .env
```

See Section 3 for required values.

### Start containers

```bash
./start-prod-env.sh --with-api
```

This starts PostgreSQL, the plagiarism worker, and the API using
`docker-compose-prod.yml`.

### Run DB migrations

```bash
bash scripts/run_db_migrations.sh
```

### Download CLIP model

The CLIP model is required before the worker can process submissions.
**Which model you need depends on your `.env` configuration:**

**Option A — OpenAI pretrained (your current setup: `CLIP_MODEL=ViT-B/32`, `CLIP_PRETRAINED=openai`)**

No manual download needed. `open_clip` downloads the model automatically
on first run directly from OpenAI's servers (~350MB). Just ensure the
container has outbound internet access on first startup.

```bash
# verify the container can reach the internet
curl -I https://openaipublic.azureedge.net
```

**Option B — LAION pretrained (`CLIP_PRETRAINED=laion2B-s32B-b82K` or similar)**

Pre-download using the provided script to avoid delays on first run:

```bash
# ViT-B-32 LAION model (~350MB)
./venv/bin/python scripts/download_clip_model.py --model ViT-B-32

# or the larger ViT-L-14 model (~900MB)
./venv/bin/python scripts/download_clip_model.py --model ViT-L-14
```

Note the model name format difference:
- `.env` uses slashes: `ViT-B/32` (open_clip format)
- download script uses dashes: `ViT-B-32` (HuggingFace repo format)

The downloaded model lands in `./models/clip/<model-name>/open_clip_pytorch_model.bin`.
Set `CLIP_LOCAL_MODEL_PATH` in `.env` to point to it.

### Install systemd user services

```bash
mkdir -p ~/.config/systemd/user

# postgres service
cat > ~/.config/systemd/user/plg_postgres.service << EOF
[Unit]
Description=PLG PostgreSQL database
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$HOME/tap_plg
ExecStart=$HOME/tap_plg/venv/bin/podman-compose -f docker-postgres.yml up -d
ExecStop=$HOME/tap_plg/venv/bin/podman-compose -f docker-postgres.yml down
TimeoutStartSec=180

[Install]
WantedBy=default.target
EOF

# app service
cat > ~/.config/systemd/user/plg_app.service << EOF
[Unit]
Description=Plagiarism App
Requires=plg_postgres.service
After=plg_postgres.service network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$HOME/tap_plg
ExecStart=$HOME/tap_plg/venv/bin/python $HOME/tap_plg/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

# enable linger so services start on boot without login
sudo loginctl enable-linger $(whoami)

systemctl --user daemon-reload
systemctl --user enable --now plg_postgres.service
systemctl --user enable --now plg_app.service
```

---

## 4. Environment Configuration (.env)

Copy `.env.example` to `.env` and update the following for production:

```bash
# RabbitMQ — CloudAMQP
RABBITMQ_HOST=<cloudamqp_host>
RABBITMQ_PORT=5672
RABBITMQ_USER=<username>
RABBITMQ_PASS=<password>
RABBITMQ_VHOST=<vhost>

# Queues
SUBMISSION_QUEUE=plagiarism_submissions
FEEDBACK_QUEUE=plagiarism_feedback
DEAD_LETTER_QUEUE=plagiarism_failed_submissions

# PostgreSQL — local container
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=plagiarism_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_a_strong_password>

# GCS
GCP_ENABLED=true
GCP_KEY_PATH=/app/credentials/gcp_service_account.json

# CLIP model
CLIP_MODEL=ViT-L/14
CLIP_PRETRAINED=laion2B-s32B-b82K
CLIP_LOCAL_MODEL_PATH=/app/models/clip/open_clip_pytorch_model.bin
USE_PGVECTOR=true

# Production settings
MOCK_GLIFIC=false
RESUBMISSION_WINDOW_DAYS=7
LOG_LEVEL=INFO
```

### GCS credentials

The `GCP_KEY_PATH` in `.env` points to `/app/credentials/gcp_service_account.json`
inside the container. The container mounts `./data` from the host. Place the
service account JSON at:

```bash
mkdir -p ~/tap_plg/data/credentials
cp /path/to/gcp_service_account.json ~/tap_plg/data/credentials/
```

Then update `docker-compose-prod.yml` to mount the credentials directory if
not already done:

```yaml
volumes:
  - ./data:/app/data
  - ./data/credentials:/app/credentials
```

---

## 5. Verify Services

```bash
# check containers are running
podman ps

# check systemd services
systemctl --user status plg_postgres.service
systemctl --user status plg_app.service

# check logs
journalctl --user -u plg_app.service -f -n 50

# check API is responding
curl -s http://localhost:8000/health
# expected: {"status": "healthy"}

# check API docs
curl -s http://localhost:8000/ | python3 -m json.tool
```

---

## 6. GCP Firewall

The API listens on port 8000. Open it in GCP:

```
GCP Console → Compute Engine → VM Instances → click instance →
Edit → Firewalls → check "Allow HTTP traffic"
```

Or add a specific rule for port 8000:

```bash
gcloud compute firewall-rules create allow-plg-api \
    --allow tcp:8000 \
    --target-tags plg-server \
    --description "Allow tap_plg API"
```

---

## 7. Updates and Redeployment

### Code changes (no requirements.txt change)

Thanks to `--layers` caching, only the code copy step reruns — the expensive
pip install layer is reused from cache. Typical time: **1-2 minutes**.

```bash
cd ~/tap_plg
git pull origin <branch>

# fast rebuild — uses cached pip layer
podman build \
    --layers \
    -f Dockerfile \
    -t localhost/tap_plg_plagiarism-checker:latest \
    .

# recreate container to pick up new image
podman stop plg-checker && podman rm plg-checker
./venv/bin/podman-compose -f docker-compose-prod.yml up -d plg-checker
podman logs --follow plg-checker
```

### Dependency changes (requirements.txt changed)

The pip install layer must be rebuilt — expect **20-30 minutes** and ensure
at least **20GB free disk space** before starting:

```bash
df -h /  # verify space
export TMPDIR=$HOME/tmp && mkdir -p $HOME/tmp

podman build \
    --layers \
    --tmpdir $HOME/tmp \
    -f Dockerfile \
    -t localhost/tap_plg_plagiarism-checker:latest \
    .
```

### .env changes

**Important:** `restart` does not pick up `.env` changes — environment
variables are baked into the container at creation time. Always remove and
recreate the container after any `.env` change:

```bash
podman stop plg-checker && podman rm plg-checker
./venv/bin/podman-compose -f docker-compose-prod.yml up -d plg-checker
podman logs --follow plg-checker
```

---

## 8. Healthcheck Fix (Dockerfile.api)

The `plg-api` container's healthcheck uses `curl` which is missing from the
final image stage. This causes the container to show as `unhealthy` in
`podman ps`. The fix is in `Dockerfile.api` — add curl to the final stage:

```dockerfile
FROM python:3.13-slim
WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
...
```

This fix is already in the repo. Rebuild after pulling:

```bash
./venv/bin/podman-compose -f docker-compose-prod.yml build api
./venv/bin/podman-compose -f docker-compose-prod.yml up -d api
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `podman-compose: command not found` | Not installed in venv | `./venv/bin/python -m pip install podman-compose` |
| Container shows `unhealthy` | `curl` missing in final image | Rebuild with updated `Dockerfile.api` (Section 8) |
| Worker not picking up messages | Wrong RabbitMQ credentials or queue name | Check `.env` — use `RABBITMQ_USER`/`RABBITMQ_PASS` not `RABBITMQ_USERNAME`/`RABBITMQ_PASSWORD` |
| `ACCESS_REFUSED - Login was refused` | Wrong RabbitMQ credentials | Verify against CloudAMQP Console → Details tab |
| `short-name did not resolve` | Podman short-name mode enforcing | Set `short-name-mode="permissive"` in `/etc/containers/registries.conf` |
| `mixing sysregistry v1/v2 is not supported` | Mixed format in registries.conf | Keep only v2 format: `unqualified-search-registries = [...]` |
| `no space left on device` during build | Disk too small for torch image (~8GB) | Increase VM disk to 80GB; use `--tmpdir $HOME/tmp` |
| `.env` changes not picked up after restart | Env vars baked into container at creation | `podman stop/rm` then `up` — never just `restart` for env changes |
| `Connect call failed ('127.0.0.1', 5433)` | Wrong `POSTGRES_PORT` or `POSTGRES_HOST` | Set `POSTGRES_HOST=plg-postgres`, `POSTGRES_PORT=5432` (internal port) |
| CNI firewall plugin version error | Old CNI config from previous failed run | `rm ~/.config/cni/net.d/tap_plg_plg-network.conflist` |
| CLIP model not loading | Model file missing | Automatic on first run if `CLIP_PRETRAINED=openai`; or run `download_clip_model.py` |
| `pg_isready` fails | PostgreSQL container not started | `systemctl --user start plg_postgres.service` |
| Services don't start on reboot | Linger not enabled | `sudo loginctl enable-linger $(whoami)` |
| `Permission denied` on data/ | Wrong ownership | `chown -R plg-dev:plg-dev ~/tap_plg/data` |
| API returns 500 on submissions | DB not initialised | Run `bash scripts/run_db_migrations.sh` |

---

## Notes

- tap_plg is **not a Frappe app** — no bench, no site, no migrate.
- Services are managed by **systemd user services**, not supervisor.
- The CLIP model is downloaded automatically on first run if using `CLIP_PRETRAINED=openai`. For LAION pretrained models, use `scripts/download_clip_model.py` to pre-download (~350MB for ViT-B-32, ~900MB for ViT-L-14).
- PostgreSQL uses **pgvector** extension for vector similarity search.
- `MOCK_GLIFIC=false` in production — set to `true` only for testing.
- `RESUBMISSION_WINDOW_DAYS=7` for production (use `RESUBMISSION_WINDOW_MINUTES=2` for testing only).
- After updating `.env`, restart the app: `systemctl --user restart plg_app.service`
- Logs: `journalctl --user -u plg_app.service -f`
