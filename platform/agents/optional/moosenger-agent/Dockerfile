# syntax=docker/dockerfile:1
# MOOSEnger specialist agent for the Prometheus platform.
#
#   prometheus_api base image  (Python 3.12, prometheus_api, a2a-sdk 1.x, uvicorn)
#     + MOOSEnger, installed from the `moosenger` build context (MOOSENGER_SRC,
#       see docker-compose.yml): the agent class and card ship in that package
#     + agent.py, a three-line launcher
#
# MOOSEnger is never vendored under platform/agents/: it imports provider SDKs
# that the platform's static tests forbid in agent source trees.
ARG PROMETHEUS_API_BASE_IMAGE_REPO=containers.github.inl.gov/genesis/prometheus_api
ARG PROMETHEUS_API_BASE_IMAGE_HASH

# Requires uv.lock. See agent-template/agent_template/Dockerfile for the rationale.
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH} AS lockfile
COPY uv.lock* /lock/
RUN [ -f /lock/uv.lock ] || { \
        echo "ERROR: uv.lock not found. Run 'uv sync' in agents/optional/moosenger-agent, commit uv.lock, and rebuild." >&2; \
        exit 1; }

FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH}

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY}

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

# MOOSEnger uses git for knowledge sync; the base image already provides it.

# 1. This launcher's own (empty) dependency set, locked.
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,from=lockfile,source=/lock/uv.lock,target=/app/uv.lock \
    uv sync --locked --no-dev --no-install-project --inexact

# 2. MOOSEnger, WITHOUT its `prometheus` extra: the extra would pull
#    prometheus_api from git, but the base image already has the platform's
#    pinned copy. Installed into the same interpreter so moosenger and
#    prometheus_api share one a2a-sdk / pydantic / starlette resolution. The
#    import check fails the build if that resolution breaks the agent.
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,from=moosenger,source=.,target=/src/moosenger,rw \
    uv pip install --system "/src/moosenger" \
    && python -c "import prometheus_api; from moosenger.a2a import prometheus_agent; print('moosenger prometheus agent OK | prometheus_api', prometheus_api.__version__)"

# 3. Launcher and config last so edits don't invalidate the dependency layers.
COPY agent.py /app/agent.py
COPY config/moosenger.yaml /app/config/moosenger.yaml

# .moosenger.yaml, vector_data/, the knowledge layout and session workspaces
# live here; docker-compose.yml backs it with a named volume.
RUN mkdir -p /workspace
ENV MOOSENGER_PROJECT_DIR=/workspace \
    MOOSENGER_CONFIG=/app/config/moosenger.yaml

EXPOSE 8000
CMD ["python", "agent.py"]
