# syntax=docker/dockerfile:1

# SearXNG metasearch for the OSTI agent's search_web tool (WEB_SEARCH_PROVIDER=searxng).
# Pinned to a dated upstream tag; bump it deliberately, since engines change with it.
FROM searxng/searxng:2026.11.9-57ff753ad

# Install any custom CA certificates (e.g. INL's TLS-inspection root) into the
# system trust store. "certs" is a named build context pointing at
# common/certs; see common/certs/setup.sh. The upstream entrypoint runs
# update-ca-certificates again at startup, which keeps them.
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh

# Not /etc/searxng: the base image declares that a VOLUME, and compose carries
# an anonymous volume over across rebuilds, so a changed settings.yml would
# never reach a recreated container.
COPY settings.yml /usr/local/searxng/osti-settings.yml
ENV SEARXNG_SETTINGS_PATH=/usr/local/searxng/osti-settings.yml
COPY start.sh /usr/local/bin/searxng-start.sh

ENTRYPOINT ["/bin/sh", "/usr/local/bin/searxng-start.sh"]
