# ==========================================
# Stage 1: Build & Dependency Resolution
# ==========================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --frozen \
    --no-dev \
    --no-install-project

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --frozen \
    --no-dev

# ==========================================
# Stage 2: Production Runtime
# ==========================================
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Install gosu and user management tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    passwd \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user
RUN useradd -u 1000 -m -s /bin/bash orchestrator

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh", "orchestrator"]
CMD ["/data/services.yaml"]
