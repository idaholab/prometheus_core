#!/bin/sh
# SearXNG refuses to start with the placeholder secret_key, and the key only
# signs its UI cookies and image-proxy URLs, neither of which this internal,
# JSON-only instance uses. Generate one per container start unless the
# deployment provides SEARXNG_SECRET.
if [ -z "${SEARXNG_SECRET:-}" ]; then
    SEARXNG_SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    export SEARXNG_SECRET
fi
exec /usr/local/searxng/entrypoint.sh "$@"
