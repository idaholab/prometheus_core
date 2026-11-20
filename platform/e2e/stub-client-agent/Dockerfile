# syntax=docker/dockerfile:1
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
# The shared viewer samples (platform/frontend/e2e/samples), from the compose
# build context of that name. Only the ones the stub hands out
COPY --from=samples part.stl model.ifc diagram.mmd results.json /app/samples/

# 8000: A2A (bearer auth). 8100: the sample files, for the backend to download
EXPOSE 8000 8100

CMD ["python", "agent.py"]
