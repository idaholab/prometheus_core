# The agents in platform/agents/ repeat these steps at the top of their own
# Dockerfiles rather than building FROM this image; keep them in step (see
# "Container images" in STANDARDS.md).
FROM ghcr.io/astral-sh/uv:0.13.6-python3.12-trixie-slim@sha256:bf889bda77474aa50c351caf1538b855ef2b7a30add45f26ca50dcb6ade06402

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.pem \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.pem \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-bundle.pem \
    UV_SYSTEM_PYTHON=1

# Install any custom CA certificates into the system trust store. "certs" is a
# named build context pointing at common/certs (passed by the Makefile, compose,
# and CI); see common/certs/setup.sh for details
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh

# Install git
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Install only dependencies (not including dev dependencies)
# This is kept separately because it will change less often than
# the next run command (when the source actually cnanges)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/src/uv.lock \
    uv export --project /src --frozen --no-dev --no-emit-project > /tmp/requirements.txt && \
    uv pip install -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install prometheus_api into python site-packages
RUN --mount=type=bind,source=pyproject.toml,target=/src/pyproject.toml \
    --mount=type=bind,source=prometheus_api,target=/src/prometheus_api/ \
    uv pip install --no-deps /src && \
    rm -rf /src/build /src/*.egg-info

# Default entrypoint is python
CMD ["python"]
