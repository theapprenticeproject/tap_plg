# tap_plg/docker/Dockerfile
#
# Multi-stage build for tap_plg plagiarism detection service.
#
# ── Build notes ───────────────────────────────────────────────────────────────
#
# The CLIP model (ViT-L/14, ~3.5 GB) is NOT baked into this image.
# It is loaded from a host-mounted volume at runtime via CLIP_LOCAL_MODEL_PATH.
#
# Before running containers, download the model once on your machine:
#
#   mkdir -p ./models/clip
#   python3 tap_plg/scripts/download_clip_model.py
#
# Then mount it in docker-compose.yml:
#   volumes:
#     - ./models:/app/models:ro
#
# This keeps the image small (~2 GB instead of ~5.5 GB) and avoids
# re-downloading the model on every image rebuild.
#
# ── Stages ────────────────────────────────────────────────────────────────────
#   base    — Python + system deps
#   deps    — pip install (cached unless requirements.txt changes)
#   runtime — final slim image

FROM python:3.11-slim AS base

# System dependencies needed by:
#   - Pillow (libpng, libjpeg, libwebp)
#   - torch / open_clip (libgomp for OpenMP)
#   - psycopg2 / asyncpg (libpq)
#   - curl (health checks in compose)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev \
    libjpeg-dev \
    libwebp-dev \
    libgomp1 \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependency stage ──────────────────────────────────────────────────────────
FROM base AS deps

# Copy requirements first — Docker layer cache means pip install only reruns
# when requirements.txt changes, not on every code change.
COPY requirements.txt .

# Install all dependencies.
# torch + open_clip are large — this layer will be cached after first build.
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM deps AS runtime

# Copy application source
COPY . .

# Create directories for runtime data
# These are overridden by volume mounts in compose but need to exist in image
RUN mkdir -p /app/models/clip \
             /app/data/faiss_index \
             /app/data/temp_images \
             /app/data/reference_images \
             /app/logs

# Default environment — overridden by compose env_file / environment blocks
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json \
    ENVIRONMENT=development

# ── Entrypoints ───────────────────────────────────────────────────────────────
# The compose file overrides the command per service:
#   tap_plg_worker: python app.py          (background consumer)
#   tap_plg_api:    uvicorn api.api:app    (FastAPI HTTP server)
#
# Default runs the worker.
CMD ["python", "app.py"]
