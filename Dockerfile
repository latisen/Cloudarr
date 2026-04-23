FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    rclone \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd -m -u 1000 cloudarr && \
    mkdir -p /config /data /mnt/torbox && \
    chown -R cloudarr:cloudarr /app /config /data /mnt/torbox

USER cloudarr

# Default environment
ENV CLOUDARR_ENV=production
ENV CLOUDARR_DB_URL=sqlite:////config/cloudarr.db
ENV CLOUDARR_LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/api/health', timeout=5)" || exit 1

# Expose API port
EXPOSE 8080

# Run API server (worker should be run as separate container or deployment)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
