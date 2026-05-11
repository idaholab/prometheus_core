# syntax=docker/dockerfile:1.7
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM mooseharbor.hpc.inl.gov/prometheus_api/prometheus_api-py312:${PROMETHEUS_API_BASE_IMAGE_HASH}

ARG MUNINN_GIT_REF

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends git openssh-client && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p -m 0700 /root/.ssh && \
    ssh-keyscan github.com github.inl.gov hpcgitlab.hpc.inl.gov >> /root/.ssh/known_hosts

# Moosenger currently initializes the public MOOSE submodule via GitHub SSH.
# Rewrite that host to HTTPS inside the image so the build does not require a
# separate GitHub.com SSH identity in the forwarded agent.
RUN git config --global url."https://github.com/".insteadOf git@github.com:

COPY pyproject.toml /app/pyproject.toml
COPY agent.py /app/agent.py
COPY agent_card.json /app/agent_card.json
COPY muninn.config.template.yaml /app/muninn.config.template.yaml

RUN --mount=type=ssh \
    --mount=type=cache,id=muninn-platform-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --system \
      "muninn @ git+ssh://git@github.inl.gov/jack-cavaluzzi/muninn.git@${MUNINN_GIT_REF}"

EXPOSE 8000

CMD ["python", "agent.py"]
