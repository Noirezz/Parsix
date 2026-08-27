FROM python:3.13-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml /app/
COPY services/made-core /app/services/made-core
COPY infra /app/infra

# Install dependencies and project in editable mode
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e /app/services/made-core

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/services/made-core/src

ENTRYPOINT ["python", "-m", "made_core.infrastructure.entrypoint"]
