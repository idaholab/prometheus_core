# syntax=docker/dockerfile:1
# The base image bundles Python 3.12, prometheus_api, and all agent
# infrastructure (a2a, starlette, uvicorn).  Its hash is pinned in the
# platform's Makefile / your .env and passed in as a build argument — you never
# edit the FROM line directly; you change PROMETHEUS_API_BASE_IMAGE_HASH.
ARG PROMETHEUS_API_BASE_IMAGE_REPO=ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel
ARG PROMETHEUS_API_BASE_IMAGE_HASH

# Requires uv.lock. The install step below mounts it from this stage, so it
# never lands in the final image. Unlike a bind mount of the file, COPY with a
# glob lets a missing uv.lock reach this readable error.
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH} AS lockfile
COPY uv.lock* /lock/
RUN [ -f /lock/uv.lock ] || { \
        echo "ERROR: uv.lock not found. Run 'uv sync' in this agent's directory, commit uv.lock, and rebuild." >&2; \
        exit 1; }

FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH}

# Accept corporate proxy settings as build arguments (optional).
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY}

WORKDIR /app

# Tell uv (the package manager) to install into the system Python — where
# prometheus_api already lives — rather than creating a separate virtualenv.
ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

# Install your agent's extra dependencies (not prometheus_api itself — it's in
# the base image), at the versions in uv.lock. --locked fails if uv.lock is out
# of date with pyproject.toml. pyproject.toml and uv.lock are mounted rather
# than copied, since they are only needed to install. The cache mount speeds up
# repeated builds on the same host.
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,from=lockfile,source=/lock/uv.lock,target=/app/uv.lock \
    uv sync --locked --no-dev --no-install-project --inexact

# Copy agent source last so code changes don't invalidate the dependency cache.
COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY prompts /app/prompts
COPY workflows /app/workflows

# Port is configured via the AGENT_PORT environment variable (default 8000).
EXPOSE ${AGENT_PORT}

CMD ["python", "agent.py"]
