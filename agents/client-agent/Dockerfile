# syntax=docker/dockerfile:1
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM mooseharbor.hpc.inl.gov/prometheus_api/prometheus_api-py312:${PROMETHEUS_API_BASE_IMAGE_HASH}

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

COPY pyproject.toml /app/
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --no-dev --no-install-project --inexact


COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY artifact_handling.py /app/artifact_handling.py
COPY conversation_store.py /app/conversation_store.py
COPY tool_discovery.py /app/tool_discovery.py
COPY capability_cache.py /app/capability_cache.py
COPY param_schema.py /app/param_schema.py
COPY planner.py /app/planner.py
COPY file_upload_handler.py /app/file_upload_handler.py
COPY orchestrator /app/orchestrator
COPY workflow_library /app/workflow_library
COPY workflows /app/workflows

EXPOSE 8000

CMD ["python", "agent.py"]
