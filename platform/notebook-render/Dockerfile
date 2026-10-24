# syntax=docker/dockerfile:1
#
# notebook-render — baked-HTML report server + dormant secret-safe re-run proxy
# for the UQ agent's generated notebooks.
#
# NOT built on the prometheus_api base image on purpose: this service runs no
# agent code. It only (a) serves an agent-generated, fully-baked static .html
# report as-is (no live kernel, never blanks) plus the extracted uq_result JSON,
# and (b) proxies a dormant /rerun to the UQ agent, injecting the Bearer
# server-side so no secret ever reaches the browser or the downloadable
# notebook. A slim Python image keeps it small and portable for HPC.
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

# Trust the corporate TLS-proxy CA before any TLS fetch, mirroring the
# frontend/backend Dockerfiles. The bundle is supplied by the `certs` build
# context (additional_contexts: { certs: ../common/certs } in docker-compose.yml).
# Without this, pip's TLS handshake to pypi.org fails behind the INL proxy
# (CERTIFICATE_VERIFY_FAILED / unable to get local issuer certificate).
# Takes every *.pem / *.crt in certs/ (the frontend Dockerfile's convention), so it
# works with whatever bundle name the checkout ships (currently certs/INL.pem).
COPY --from=certs . /tmp/certs/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && for f in /tmp/certs/*.pem /tmp/certs/*.crt; do \
         [ -e "$f" ] && cp "$f" "/usr/local/share/ca-certificates/$(basename "${f%.*}").crt"; \
       done; \
    update-ca-certificates \
    && rm -rf /var/lib/apt/lists/* /tmp/certs
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY notebook-render/requirements.txt /app/requirements.txt
RUN --mount=type=cache,id=notebook-render-pip,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt \
    && python -m ipykernel install --name python3 --display-name "Python 3"

COPY notebook-render/proxy.py /app/proxy.py

# Container port 8000 — the platform convention every service on agent-network
# follows (nginx and the vite dev proxy address it there; the host-port map in
# compose exposes it at 8876 for hybrid dev).
EXPOSE 8000

# The proxy is the front door: it serves /render/{id} (baked static HTML rooted
# at NOTEBOOK_DIR), /result/{id} (extracted uq_result JSON), and the dormant
# /rerun. Both bare and /notebook-prefixed routes are registered. PID 1.
CMD ["uvicorn", "proxy:app", "--host", "0.0.0.0", "--port", "8000"]
