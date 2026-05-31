# Multi-stage Dockerfile for Nakh FastAPI Application

# Stage 1: Build stage
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Switch to accessible mirror
RUN sed -i 's|http://deb.debian.org|http://mirror.arvancloud.ir|g' /etc/apt/sources.list.d/*.sources 2>/dev/null; \
    sed -i 's|http://deb.debian.org|http://mirror.arvancloud.ir|g' /etc/apt/sources.list 2>/dev/null; \
    true

# Force-downgrade base libs to match stale mirror, then install build deps
RUN apt-get -o Acquire::Check-Valid-Until=false update && \
    apt-get install -y --allow-downgrades \
    libc6=2.36-9+deb12u13 libssl3=3.0.18-1~deb12u2 && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Stage 2: Production stage
FROM python:3.11-slim-bookworm

WORKDIR /app

# Switch to accessible mirror
RUN sed -i 's|http://deb.debian.org|http://mirror.arvancloud.ir|g' /etc/apt/sources.list.d/*.sources 2>/dev/null; \
    sed -i 's|http://deb.debian.org|http://mirror.arvancloud.ir|g' /etc/apt/sources.list 2>/dev/null; \
    true

# Install runtime dependencies (allow downgrades to align with stale mirror)
RUN apt-get -o Acquire::Check-Valid-Until=false update && \
    apt-get install -y --no-install-recommends --allow-downgrades \
    libpq5 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r nakh && useradd -r -g nakh nakh

# Copy wheels from builder stage
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir /wheels/*

# Copy application code
COPY --chown=nakh:nakh . .

# Create directories
RUN mkdir -p /app/media /app/logs && chown -R nakh:nakh /app/media /app/logs

# Switch to non-root user
USER nakh

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
