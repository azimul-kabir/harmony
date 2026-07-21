FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    sqlite3 \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL=/root/.deno

ENV PATH="${DENO_INSTALL}/bin:${PATH}"

# `pyproject.toml` is the canonical dependency manifest.  Install the
# application distribution so production images include the mandatory
# filesystem watcher dependency.
COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --upgrade pip \
    && pip install --no-cache-dir .

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
