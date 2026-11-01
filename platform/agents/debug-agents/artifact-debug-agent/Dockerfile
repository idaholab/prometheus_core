# syntax=docker/dockerfile:1
# Both are passed in by the platform's compose files, from platform/Makefile
# or platformctl. No default here: build with make, not a bare docker build
ARG PROMETHEUS_API_BASE_IMAGE_REPO
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    uv sync --locked --no-dev --no-install-project --inexact


COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY workflows /app/workflows

EXPOSE 8000

CMD ["python", "agent.py"]
