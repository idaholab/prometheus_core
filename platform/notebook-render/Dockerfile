# syntax=docker/dockerfile:1
#
# notebook-render: serves the baked HTML reports of agent-generated UQ notebooks.
#
# Not built on the prometheus_api base image on purpose: this service runs no
# agent code. It serves an agent-generated, fully baked static .html report as-is
# (no live kernel, so it never comes up blank). A slim Python image keeps it small.
# Pinned like the backend and SDK images (python 3.12, Debian trixie; pip and
# apt work as on python:slim).
FROM ghcr.io/astral-sh/uv:0.13.6-python3.12-trixie-slim@sha256:bf889bda77474aa50c351caf1538b855ef2b7a30add45f26ca50dcb6ade06402

# Build args for INL hosts (mirrors the platform's build-arg convention).
# PROMETHEUS_API_BASE_IMAGE_HASH is passed by the shared compose anchor but
# unused here (this image is not built on the prometheus_api base) — declared
# only so Compose does not warn about an unconsumed build arg.
ARG PROMETHEUS_API_BASE_IMAGE_HASH=""
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install any custom CA certificates into the system trust store before pip
# reaches PyPI, as in the backend and sdk Dockerfiles ("certs" is the named
# build context for common/certs; see common/certs/setup.sh).
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh
ENV PIP_CERT=/etc/ssl/certs/ca-bundle.pem \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.pem \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.pem

COPY notebook-render/requirements.txt /app/requirements.txt
RUN --mount=type=cache,id=notebook-render-pip,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY notebook-render/proxy.py /app/proxy.py

# Container port 8000 — the platform convention every service on agent-network
# follows (nginx and the vite dev proxy address it there; the host-port map in
# compose exposes it at 8876 for hybrid dev).
EXPOSE 8000

# Serves /render/{id} (baked static HTML under NOTEBOOK_DIR) and /health, bare and
# /notebook-prefixed. PID 1.
CMD ["uvicorn", "proxy:app", "--host", "0.0.0.0", "--port", "8000"]
