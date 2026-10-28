# syntax=docker/dockerfile:1
ARG PROMETHEUS_API_BASE_IMAGE_REPO=containers.github.inl.gov/genesis/prometheus_api
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:${PROMETHEUS_API_BASE_IMAGE_HASH}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy \
    DOCLING_ARTIFACTS_PATH="/root/.cache/docling/models"

COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project --inexact && \
    uv run docling-tools models download \
        --output-dir "${DOCLING_ARTIFACTS_PATH}" \
        layout tableformer rapidocr

COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY research_agent /app/research_agent
# The evaluation harness runs in this container: `make osti-eval`.
COPY evals /app/evals

EXPOSE 8000

CMD ["python", "agent.py"]
