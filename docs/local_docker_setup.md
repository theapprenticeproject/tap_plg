# Local Docker setup for tap_plg

This guide runs the `tap_plg` FastAPI API, worker, and Postgres database through the root local Docker stack.

The recommended path is:

```sh
cd /Users/TAP/Documents/Git/LMS
cp .env.example env.local
./scripts/start_local_docker.sh
```

## Services

The root Compose file starts:

- `plg-postgres`: Postgres 16 with pgvector.
- `plg-api`: FastAPI service from `Dockerfile.api`.
- `plg-worker`: plagiarism processing worker from `Dockerfile`.

The database schema is loaded from:

```text
tap_plg/database/init.sql
```

## External RabbitMQ

RabbitMQ is created externally in CloudAMQP:

```text
https://customer.cloudamqp.com/login
```

Fill these root `env.local` values:

```dotenv
RABBITMQ_HOST=
RABBITMQ_PORT=5672
RABBITMQ_VIRTUAL_HOST=
RABBITMQ_USERNAME=
RABBITMQ_PASSWORD=
PLG_SUBMISSION_QUEUE=plagiarism_submissions
PLG_FEEDBACK_QUEUE=plagiarism_feedback
```

The API publishes submissions to `PLG_SUBMISSION_QUEUE`. The worker consumes from that queue and publishes results to `PLG_FEEDBACK_QUEUE`.

## Required settings

The active folders reviewed were:

- `api`
- `config`
- `database`
- `image_worker`
- `mq`
- `plag_checker`
- `processors`

The app expects these environment-backed settings:

- Postgres: `PLG_POSTGRES_DB`, `PLG_POSTGRES_USER`, `PLG_POSTGRES_PASSWORD`, `PLG_POSTGRES_PORT`.
- RabbitMQ: shared `RABBITMQ_*` values plus `PLG_SUBMISSION_QUEUE` and `PLG_FEEDBACK_QUEUE`.
- GCP: optional `PLG_GCP_KEY_PATH`, mounted from `tap_plg/app/credentials`.
- CLIP model: optional `PLG_CLIP_LOCAL_MODEL_PATH`, mounted from `tap_plg/data/models`.
- Detection thresholds: duplicate, semantic, hash, and image validation values in root `env.local`.

For a basic local API smoke test, RabbitMQ and Postgres are enough. For real image plagiarism checks, configure GCP credentials and ensure the CLIP model can be downloaded or mounted locally.

## Open the API

```text
http://localhost:8002/docs
```

Health check:

```text
http://localhost:8002/health
```

## Useful commands

View API logs:

```sh
docker compose --env-file env.local -f docker/local/docker-compose.yml logs -f plg-api
```

View worker logs:

```sh
docker compose --env-file env.local -f docker/local/docker-compose.yml logs -f plg-worker
```

Restart only tap_plg:

```sh
docker compose --env-file env.local -f docker/local/docker-compose.yml up -d --build plg-postgres plg-api plg-worker
```
