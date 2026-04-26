FROM python:3.12-slim

LABEL org.opencontainers.image.title="coursemap"
LABEL org.opencontainers.image.description="Massey University degree planner"
LABEL org.opencontainers.image.source="https://github.com/bonniemcconnell/coursemap"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[api]"

# Copy source + datasets
COPY coursemap/ ./coursemap/
COPY datasets/   ./datasets/

# Non-root user for security
RUN useradd -m -u 1000 coursemap && chown -R coursemap:coursemap /app
USER coursemap

EXPOSE 8080

# WORKERS defaults to 2; override via env var for higher-traffic deployments
ENV WORKERS=2

# Healthcheck so orchestrators know when the app is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:8080/api || exit 1

CMD uvicorn coursemap.api.server:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers ${WORKERS} \
    --proxy-headers \
    --forwarded-allow-ips "*"
