# syntax=docker/dockerfile:1

# ---- base (shared) ----
FROM node:22.19.0-bookworm-slim AS base
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# update-ca-certificates only picks up *.crt files, so normalize the extension
COPY --from=certs . /tmp/certs/
RUN for f in /tmp/certs/*.pem /tmp/certs/*.crt; do \
      [ -e "$f" ] && cp "$f" "/usr/local/share/ca-certificates/$(basename "${f%.*}").crt"; \
    done; \
    update-ca-certificates \
 && rm -rf /tmp/certs

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
COPY frontend/. .
EXPOSE 5150
ENV HOST=0.0.0.0
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5150"]

# ---- build (prod) ----
FROM deps AS build
COPY frontend/. .
RUN npm run build

# ---- prod ----
FROM nginx:alpine AS prod
# The nginx image renders /etc/nginx/templates/*.template into conf.d/ at start,
# substituting ${BACKEND_UPSTREAM}.
ENV BACKEND_UPSTREAM=http://backend:8000
COPY frontend/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
