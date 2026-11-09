# syntax=docker/dockerfile:1
# Standalone FastAPI backend. Not built FROM the prometheus_api base image (unlike
# the agents): the app imports prometheus_api.{a2a_stream,contract,storage_client}
# at runtime, so this Dockerfile installs the package from the checked-out SDK
# instead. Two named build contexts are required (docker-compose.yml and CI pass
# them; `--build-context` on the CLI):
#   sdk    the repo's sdk/ directory (pyproject.toml, uv.lock, prometheus_api/)
#   certs  the repo's common/certs directory (CA certs + setup.sh)
#
# The base is the same pinned uv + Python 3.12 image sdk/Dockerfile builds on.
FROM ghcr.io/astral-sh/uv:0.13.7-python3.12-trixie-slim@sha256:d4a752dd52f42e0c508bb0b6a912f15922bb32e42f66af30671c3fdc0d759f21

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.pem \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.pem \
    UV_SYSTEM_PYTHON=1

# Install any custom CA certificates into the system trust store, as in
# sdk/Dockerfile (see common/certs/setup.sh for details)
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh

# The layers from here to the dependency installs depend on nothing in the build
# contexts, so they sit above them: a change to the SDK or the app never re-runs them.

# VTK (added in pyproject.toml for the Exodus/STL→VTP mesh pipeline) links libGL and
# a few X client libs at `import vtk`, even though the pipeline only uses headless
# IO/filters (no rendering context). The base is a Debian-based Python image, so
# install them via apt. If a mesh render 500s with
# "libGL.so.1: cannot open shared object file", this layer is the fix.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*

# Fixed non-root UID so the image works under Pod Security "restricted" and with a
# read-only root filesystem. USER is set at the end, after everything that needs root.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --home-dir /home/app --create-home app

# Root of the persistent cache volumes (compose mounts mesh-cache at
# /cache/prometheus-mesh), owned by the non-root app UID. The mount point itself
# must exist in the image: a fresh named volume copies its ownership, and one Docker
# creates on mount would be root-owned.
RUN mkdir -p /cache/prometheus-mesh && chown -R 10001:10001 /cache

# prometheus_api dependencies, from the SDK's lockfile. Kept apart from the package
# install so it only re-runs when the SDK's dependencies change.
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,from=sdk,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,from=sdk,source=uv.lock,target=/src/uv.lock \
    uv export --project /src --frozen --no-dev --no-emit-project > /tmp/sdk-requirements.txt && \
    uv pip install -r /tmp/sdk-requirements.txt && \
    rm /tmp/sdk-requirements.txt

# prometheus_api itself, into site-packages
RUN --mount=type=bind,from=sdk,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,from=sdk,source=prometheus_api,target=/src/prometheus_api/ \
    uv pip install --no-deps /src

WORKDIR /app

# `prometheus-api` is a dev-only dependency in pyproject.toml, sourced from
# ../../sdk via [tool.uv.sources] for local tests. It is already installed above,
# and that path isn't in this build context, so:
#   --no-dev       exclude the dev group (we don't reinstall prometheus-api)
#   --no-sources   ignore [tool.uv.sources] entirely, so uv never looks for the
#                  path while resolving (the deciding flag — --no-dev alone still
#                  resolves the source)
#   --inexact      keep the prometheus-api + deps installed above
#   --no-install-project  don't install backend itself; the code is COPYed below
ENV UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_LINK_MODE=copy

COPY pyproject.toml /app/
RUN --mount=type=cache,id=prometheus-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --no-dev --no-install-project --inexact --no-sources

# Application files, least to most frequently changed.
#
# Alembic migrations for the admin plane (users, OIDC providers, signing keys) --
# applied by docker-entrypoint.sh before uvicorn starts, NOT from the app's lifespan
# (which would migrate once per worker; see the entrypoint for why).
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
# Brings app/config.yml along with the package sources.
COPY app /app/app

# Everything above stays root-owned (the app only reads /app and site-packages)
# except /cache; the only writable paths are /tmp (tempfile: uploads, artifact
# downloads, mesh sources) and /cache. HOME and XDG_CACHE_HOME are set only now,
# so they don't redirect uv's cache (the mount above) while installing as root.
ENV HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache
USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
