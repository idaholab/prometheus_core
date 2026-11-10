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
# Installed as root (the npm cache mount is root's), then handed to the image's
# `node` user. The dev server writes its dependency cache to node_modules/.vite and
# compose may run it as the developer's own UID instead (see frontend-dev), so
# node_modules is also writable by any UID. In the same RUN so node_modules isn't
# stored twice.
RUN --mount=type=cache,id=prometheus-npm-cache,target=/root/.npm,sharing=locked \
    { npm ci --no-audit --no-fund --include=optional || \
      npm install --no-audit --no-fund --include=optional; } \
    && chown -R node:node /app \
    && chmod -R a+rwX /app/node_modules

# ---- dev ----
FROM deps AS dev
# No source COPY: docker-compose.yml bind-mounts ./frontend over /app (keeping the
# image's node_modules), so source edits never need an image rebuild
EXPOSE 5150
# HOME=/tmp: a developer UID with no passwd entry gets HOME=/, which npm can't write
# its logs and cache to. With a read-only root, /tmp must allow exec (tmpfs
# /tmp:exec, or a Kubernetes emptyDir): @swc/core unpacks its native addon into
# $HOME/.cache and loads it from there, and refuses a noexec mount.
ENV HOST=0.0.0.0 \
    HOME=/tmp
# The node image's `node` user, by number (hadolint DL3066)
USER 1000:1000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5150"]

# ---- build (prod) ----
FROM deps AS build
# Only what `tsc && vite build` reads, so the README, nginx config and the like
# don't invalidate the bundle. Config first, then the sources that change most.
COPY frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN npm run build

# ---- prod ----
# The unprivileged variant runs as UID 101 and keeps its pid and temp files in
# /tmp, so it works with a read-only root filesystem.
FROM nginxinc/nginx-unprivileged:1.31.7-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e AS prod
# The nginx image renders /etc/nginx/templates/*.template at start, substituting
# ${BACKEND_UPSTREAM}. It renders into /tmp rather than conf.d/, which isn't
# writable with a read-only root (nginx would then start on the stock config,
# with no /api proxy or /healthz); conf.d/default.conf just includes the result.
ENV BACKEND_UPSTREAM=http://backend:8000 \
    NGINX_ENVSUBST_OUTPUT_DIR=/tmp
# --chown: COPY keeps the checkout's file mode (0600 under `umask 077`), and the
# entrypoint now reads this as UID 101, not root. Owned by 101 it's readable at any
# mode. Don't add --chmod: it also applies to the templates/ directory COPY creates,
# and 0644 there drops the execute bit, so nginx can't open the file at all.
COPY --chown=101:101 frontend/nginx/default.conf.template /etc/nginx/templates/default.conf.template
# Pin the user rather than inheriting the base image's, so a base bump can't
# change the UID the chart's runAsUser expects. 101 owns conf.d/, so the next
# step needs no root; if a base bump changes that, the build fails here.
USER 101:101
RUN echo 'include /tmp/default.conf;' > /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
