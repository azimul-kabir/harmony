# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0 \
    HOME=/tmp/harmony \
    XDG_CONFIG_HOME=/tmp/harmony/.config \
    HARMONY_SPOTDL_CONFIG_DIR=/tmp/harmony/.config/spotdl

WORKDIR /app

# Install system dependencies in one cached layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno into a path accessible to the unprivileged Synology UID/GID
# selected by Compose. Installing under /root makes it invisible at runtime.
RUN export DENO_INSTALL=/tmp/deno-install \
    && curl -fsSL https://deno.land/install.sh | sh \
    && install -m 0755 /tmp/deno-install/bin/deno /usr/local/bin/deno \
    && rm -rf /tmp/deno-install \
    && deno --version

# Copy dependency metadata first so dependency installation remains cached
# when only application source files change.
COPY pyproject.toml README.md ./

# The package currently requires the app directory during installation.
COPY app ./app

# Reuse downloaded Python packages between builds.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip \
    && python -m pip install .

# Copy remaining project files after dependency installation.
COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent http://localhost:8080/health/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
