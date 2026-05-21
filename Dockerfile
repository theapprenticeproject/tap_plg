FROM python:3.13-slim as builder

WORKDIR /app

# Install build dependencies in a single layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    vim \
    gcc \
    g++ \
    git \
    wget \
    ca-certificates \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for better caching
COPY requirements.txt .

# Install to explicit location
RUN python -m pip install --no-cache-dir --upgrade setuptools wheel && \
    python -m pip install --prefix=/install -r requirements.txt --no-cache-dir

# ============================================
# Final stage - minimal runtime image
# ============================================
FROM python:3.13-slim

WORKDIR /app

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create necessary directories
RUN mkdir -p /app/data /app/logs /root/.cache/clip

RUN ls

# Copy application code (do this last for better caching)
COPY . .


CMD ["python", "app.py"]
