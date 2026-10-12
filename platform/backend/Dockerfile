# syntax=docker/dockerfile:1
# Standalone FastAPI backend. Not built FROM the prometheus_api base image (unlike
# the agents): the app imports prometheus_api.{a2a_stream,contract,storage_client}
# at runtime, so this Dockerfile installs the package from the checked-out SDK
# instead. Two named build contexts are required (docker-compose.yml and CI pass
# them; `--build-context` on the CLI):
#   sdk    the repo's sdk/ directory (pyproject.toml, uv.lock, prometheus_api/)
#   certs  directory of extra CA *.pem files (platform/certs)
#
# The base is the same pinned uv + Python 3.12 image sdk/Dockerfile builds on.
FROM ghcr.io/astral-sh/uv:0.11.25-python3.12-trixie-slim@sha256:1b9ee30381d729b07044688631ba4473c72db5c048a5f2a504c40186e65efb86

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.pem \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.pem \
    UV_SYSTEM_PYTHON=1

# Set up CA certificate bundle: start with system certs, append custom if provided
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    cp /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-bundle.pem 2>/dev/null || true; \
    if ls /tmp/certs/*.pem 1>/dev/null 2>&1; then \
        cat /tmp/certs/*.pem >> /etc/ssl/certs/ca-bundle.pem; \
    fi

# prometheus_api dependencies, from the SDK's lockfile. Kept apart from the package
# install so it only re-runs when the SDK's dependencies change.
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,from=sdk,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,from=sdk,source=uv.lock,target=/src/uv.lock \
    cd /src && \
    uv export --frozen --no-dev --no-emit-project > /tmp/sdk-requirements.txt && \
    uv pip install -r /tmp/sdk-requirements.txt && \
    rm /tmp/sdk-requirements.txt

# prometheus_api itself, into site-packages
RUN --mount=type=bind,from=sdk,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,from=sdk,source=prometheus_api,target=/src/prometheus_api/ \
    cd /src && \
    uv pip install --no-deps /src

WORKDIR /app

# `prometheus-api` is a dev-only dependency in pyproject.toml, pinned to a private
# git branch via [tool.uv.sources] for local tests. It is already installed above,
# and at image build time we must NOT fetch that private repo, so:
#   --no-dev       exclude the dev group (we don't reinstall prometheus-api)
#   --no-sources   ignore [tool.uv.sources] entirely, so uv never clones the git
#                  repo while resolving the lock (the deciding flag — --no-dev alone
#                  still resolves the source)
#   --inexact      keep the prometheus-api + deps installed above
#   --no-install-project  don't install backend itself; the code is COPYed below
ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

# VTK (added in pyproject.toml for the Exodus/STL→VTP mesh pipeline) links libGL and
# a few X client libs at `import vtk`, even though the pipeline only uses headless
# IO/filters (no rendering context). The base is a Debian-based Python image, so
# install them via apt. If a mesh render 500s with
# "libGL.so.1: cannot open shared object file", this layer is the fix.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --no-dev --no-install-project --inexact --no-sources

# Brings app/config.yml along with the package sources.
COPY app /app/app

# Alembic migrations for the admin plane (users, OIDC providers, signing keys) --
# applied by docker-entrypoint.sh before uvicorn starts, NOT from the app's lifespan
# (which would migrate once per worker; see the entrypoint for why).
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
