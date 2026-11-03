# syntax=docker/dockerfile:1

# ---- base (shared) ----
FROM node:22.23.3-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9 AS base
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Install any custom CA certificates into the system trust store. "certs" is a
# named build context pointing at common/certs (passed by compose and CI); see
# common/certs/setup.sh for details
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh

ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    NPM_CONFIG_cafile=/etc/ssl/certs/ca-certificates.crt

# ---- deps ----
FROM base AS deps
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,id=prometheus-npm-cache,target=/root/.npm,sharing=locked \
    npm ci --no-audit --no-fund --include=optional || \
    npm install --no-audit --no-fund --include=optional

# ---- dev ----
FROM deps AS dev
# No source COPY: docker-compose.yml bind-mounts ./frontend over /app (keeping the
# image's node_modules), so source edits never need an image rebuild
EXPOSE 5150
ENV HOST=0.0.0.0
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5150"]

# ---- dev-src (make cluster-dev) ----
# The dev stage plus the source, for a pod: it can't bind-mount ./frontend the way
# Compose does. Tilt then syncs edits into /app and Vite's HMR picks them up.
FROM dev AS dev-src
COPY frontend/ ./

# ---- build (prod) ----
FROM deps AS build
# Only what `tsc && vite build` reads, so the README, nginx config and the like
# don't invalidate the bundle. Config first, then the sources that change most.
COPY frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN npm run build

# ---- prod ----
FROM nginx:1.31.8-alpine@sha256:785835ea65db4bba6f021acc0f3be91b0fef76a53fe41f8588c6698d2aed0606 AS prod
# The nginx image renders /etc/nginx/templates/*.template into conf.d/ at start,
# substituting ${BACKEND_UPSTREAM}.
ENV BACKEND_UPSTREAM=http://backend:8000
COPY frontend/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
