# syntax=docker/dockerfile:1
# Installs prometheus_api from the checked-out SDK, as backend/Dockerfile does,
# rather than building FROM the prometheus_api base image: a FROM image keys
# the build cache on its digest, which only the published image has. Named
# build contexts (docker-compose / publish.yml pass them):
#   sdk    the repo's sdk/ directory
#   certs  the repo's common/certs directory
# Keep these steps identical in every agent Dockerfile and in step with
# sdk/Dockerfile (see "Container images" in STANDARDS.md).
FROM ghcr.io/astral-sh/uv:0.13.6-python3.12-trixie-slim@sha256:bf889bda77474aa50c351caf1538b855ef2b7a30add45f26ca50dcb6ade06402

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.pem \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.pem \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-bundle.pem \
    UV_SYSTEM_PYTHON=1

RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,from=sdk,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,from=sdk,source=uv.lock,target=/src/uv.lock \
    uv export --project /src --frozen --no-dev --no-emit-project > /tmp/sdk-requirements.txt && \
    uv pip install -r /tmp/sdk-requirements.txt && \
    rm /tmp/sdk-requirements.txt

RUN --mount=type=bind,from=sdk,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,from=sdk,source=prometheus_api,target=/src/prometheus_api/ \
    uv pip install --no-deps /src

# The agent's own steps from here
WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    uv sync --locked --no-dev --no-install-project --inexact


COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY artifact_handling.py /app/artifact_handling.py
COPY conversation_store.py /app/conversation_store.py
COPY tool_discovery.py /app/tool_discovery.py
COPY capability_cache.py /app/capability_cache.py
COPY param_schema.py /app/param_schema.py
COPY file_upload_handler.py /app/file_upload_handler.py
COPY task_graph.py /app/task_graph.py
COPY prompts /app/prompts
COPY orchestrator /app/orchestrator
COPY workflow_library /app/workflow_library
COPY workflows /app/workflows

EXPOSE 8000

CMD ["python", "agent.py"]
