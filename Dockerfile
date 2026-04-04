# --- Builder stage ---
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install gnmic
ARG GNMIC_VERSION=0.45.0
RUN curl -sL https://github.com/openconfig/gnmic/releases/download/v${GNMIC_VERSION}/gnmic_${GNMIC_VERSION}_Linux_x86_64.tar.gz \
    | tar xz -C /usr/local/bin gnmic \
    && chmod +x /usr/local/bin/gnmic

WORKDIR /app

# Install Python dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Clone YANG models
ARG YANG_MODELS_TAG=v24.10.1
RUN git clone -b ${YANG_MODELS_TAG} --depth 1 https://github.com/nokia/srlinux-yang-models \
    && rm -rf srlinux-yang-models/.git

# Copy source and install the project
COPY src/ src/
RUN uv sync --frozen

# Pre-build YANG index so startup is instant
ENV PATH="/app/.venv/bin:$PATH"
RUN python -c "from srl_explorer.tools.yang import build_or_load_yang_index; from pathlib import Path; build_or_load_yang_index(Path('./srlinux-yang-models/srlinux-yang-models'), Path('.cache'))"

# --- Runtime stage ---
FROM python:3.12-slim

# Copy gnmic
COPY --from=builder /usr/local/bin/gnmic /usr/local/bin/gnmic

WORKDIR /app

# Copy venv and project files
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/src src
COPY --from=builder /app/srlinux-yang-models srlinux-yang-models
COPY --from=builder /app/.cache .cache
RUN chmod -R a+rw .cache

# .env passed at runtime via --env-file
# logs/ written at runtime, mount via -v to persist
# Container runs as the invoking user via --user in docker run

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["srl-explorer"]
