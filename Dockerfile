# ─────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for mini-agent-orchestrator
# Target: ~200MB image (Python 3.11-slim + production deps only)
#
# Interview: "Multi-stage build keeps the final image small by excluding
# build tools, test dependencies, and pip cache from the runtime layer."
# ─────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ─────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy only dependency files first (cache-friendly layer ordering)
COPY pyproject.toml .
COPY src/ src/

# Build wheel and install production deps into /install
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ src/

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Switch to non-root
USER appuser

# Environment defaults
ENV ORCHESTRATOR_HOST=0.0.0.0 \
    ORCHESTRATOR_PORT=8000 \
    ORCHESTRATOR_REGISTRY_BACKEND=memory \
    ORCHESTRATOR_WORKFLOW_BACKEND=memory \
    ORCHESTRATOR_MAX_CONCURRENCY=10 \
    ORCHESTRATOR_LOG_LEVEL=INFO

EXPOSE 8000

# Health check — liveness probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with uvicorn
CMD ["python", "-m", "uvicorn", "agent_orchestrator.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
