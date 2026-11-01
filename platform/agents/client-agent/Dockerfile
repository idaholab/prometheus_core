# syntax=docker/dockerfile:1
# Both are passed in by the platform's compose files, from platform/Makefile
# or platformctl. No default here: build with make, not a bare docker build
ARG PROMETHEUS_API_BASE_IMAGE_REPO
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH}

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
