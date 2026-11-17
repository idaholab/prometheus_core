#!/usr/bin/env bash
# Dev only: build this checkout's OSTI agent and run it attached to a platform
# stack that is already up (started with `make up OPTIONAL_AGENTS=true`
# elsewhere). See docker-compose.attach.yml for why each piece is needed.
#
#   ./dev-attach.sh          rebuild and (re)start the agent, wait until healthy
#   ./dev-attach.sh --logs   follow the agent's logs
#   ./dev-attach.sh --down   stop and remove the dev agent (and osti-searxng)
#
# The platform directory (for its .env) is taken from the running backend
# container; set PLATFORM_DIR to choose one explicitly.
set -euo pipefail

cd "$(dirname "$0")"

PROJECT=osti-dev
SERVICE=osti-research-agent
PLATFORM_PROJECT=${PLATFORM_PROJECT:-prometheus_platform}

die() { echo "dev-attach: $*" >&2; exit 1; }

platform_dir=${PLATFORM_DIR:-$(docker ps \
    --filter "label=com.docker.compose.project=$PLATFORM_PROJECT" \
    --filter "label=com.docker.compose.service=backend" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' | head -n 1)}
[ -n "$platform_dir" ] || die "no running $PLATFORM_PROJECT backend; start the platform, or set PLATFORM_DIR"
env_file="$platform_dir/.env"
[ -f "$env_file" ] || die "$env_file not found"

# env -i: compose lets exported shell variables win over --env-file, so a
# stale AGENT_SECRET in this shell would make the backend and agent reject
# each other (401).
compose() {
    env -i HOME="$HOME" PATH="$PATH" \
        PROMETHEUS_API_BASE_IMAGE_REPO=prometheus_api \
        PROMETHEUS_API_BASE_IMAGE_HASH=local \
        docker compose -p "$PROJECT" --env-file "$env_file" \
        -f docker-compose.yml -f docker-compose.attach.yml "$@"
}

case "${1:-}" in
    --logs) compose logs -f "$SERVICE"; exit ;;
    --down) compose down; exit ;;
    "") ;;
    *) die "unknown option $1 (use --logs or --down)" ;;
esac

# Both containers would answer to the osti-research-agent name on the shared
# network, and calls would reach either one.
old=$(docker ps \
    --filter "label=com.docker.compose.project=$PLATFORM_PROJECT" \
    --filter "label=com.docker.compose.service=$SERVICE" \
    --format '{{.Names}}')
[ -z "$old" ] || die "the platform's own agent is running; stop it first: docker stop $old"

docker image inspect prometheus_api:local >/dev/null 2>&1 ||
    die "base image prometheus_api:local is missing; build it with: make -C $platform_dir base-image"

echo "Platform: $platform_dir"
compose up -d --build "$SERVICE"

printf 'Waiting for %s to be healthy' "$SERVICE"
for _ in $(seq 1 36); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$SERVICE" 2>/dev/null || true)
    case "$status" in
        healthy) echo " - ok"; exit 0 ;;
        unhealthy) echo; die "$SERVICE is unhealthy; see ./dev-attach.sh --logs" ;;
    esac
    printf '.'
    sleep 5
done
echo
die "$SERVICE was not healthy after 3 minutes; see ./dev-attach.sh --logs"
