# syntax=docker/dockerfile:1
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM containers.github.inl.gov/genesis/prometheus_api:${PROMETHEUS_API_BASE_IMAGE_HASH}

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

COPY pyproject.toml /app/
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --no-dev --no-install-project --inexact


COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY samples /app/samples

EXPOSE 8000

CMD ["python", "agent.py"]
