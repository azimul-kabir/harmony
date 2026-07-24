# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0 \
    DENO_INSTALL=/root/.deno \
    PATH="/root/.deno/bin:${PATH}"

WORKDIR /app

# Install system dependencies in one cached layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        sqlite3 \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno.
RUN curl -fsSL https://deno.land/install.sh | sh

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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
