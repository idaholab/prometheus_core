#!/usr/bin/env bash
# Check that /api/events streams through the ingress without being buffered.
#
# The endpoint sends a ": connected" comment the moment a client connects, then
# a ": ping" every 15 seconds, and never finishes on its own. A buffering proxy
# holds those bytes back, so this opens the stream, waits a few seconds and
# requires both that the first frame arrived and that the connection was still
# open when curl gave up (exit 28, the timeout).
#
# /api/events needs a session. With SSE_CHECK_USERNAME and SSE_CHECK_PASSWORD
# set, this logs in as that user, on any cluster at any time. Without them it
# creates the first admin through /api/setup/bootstrap, which only works on a
# platform that hasn't been set up yet (a fresh cluster, as in CI) and leaves a
# "smoke-check" admin behind.
#
# Usage: check-sse-stream.sh [base-url] [seconds-to-wait]
set -euo pipefail

base="${1:-http://localhost:8080}"
wait_seconds="${2:-6}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
jar="$work/cookies"

# post <path> <json>: prints the HTTP status; the session cookie lands in $jar on success
post() {
  curl -sS -o /dev/null -w '%{http_code}' -c "$jar" \
    -H 'Content-Type: application/json' -d "$2" "$base$1"
}

if [ -n "${SSE_CHECK_USERNAME:-}" ] && [ -n "${SSE_CHECK_PASSWORD:-}" ]; then
  body="$(SSE_U="$SSE_CHECK_USERNAME" SSE_P="$SSE_CHECK_PASSWORD" python3 -c \
    'import json, os; print(json.dumps({"username": os.environ["SSE_U"], "password": os.environ["SSE_P"]}))')"
  status="$(post /api/auth/login "$body")"
  if [ "$status" != 200 ]; then
    echo "[ERROR] POST $base/api/auth/login returned $status for SSE_CHECK_USERNAME" >&2
    exit 1
  fi
else
  password="smoke-check-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  status="$(post /api/setup/bootstrap "{\"username\":\"smoke-check\",\"password\":\"$password\"}")"
  if [ "$status" = 409 ]; then
    echo "[ERROR] The platform is already set up, so this check can't create its user." >&2
    echo "        Set SSE_CHECK_USERNAME and SSE_CHECK_PASSWORD to log in as an existing user." >&2
    exit 1
  elif [ "$status" != 200 ]; then
    echo "[ERROR] POST $base/api/setup/bootstrap returned $status" >&2
    exit 1
  fi
fi

# --max-time ends the otherwise endless stream. -N turns off curl's own
# buffering, so what lands in the file is what the proxy let through.
set +e
curl -s -N --max-time "$wait_seconds" -b "$jar" -D "$work/headers" -o "$work/stream" \
  "$base/api/events"
rc=$?
touch "$work/stream" "$work/headers"
set -e

if [ "$rc" -ne 28 ]; then
  echo "[ERROR] /api/events ended on its own (curl exit $rc) instead of staying open" >&2
  cat "$work/headers" 2>/dev/null >&2 || true
  exit 1
fi
if ! grep -qi '^content-type: *text/event-stream' "$work/headers"; then
  echo "[ERROR] /api/events did not answer with text/event-stream:" >&2
  cat "$work/headers" >&2
  exit 1
fi
if ! grep -q '^: connected' "$work/stream"; then
  echo "[ERROR] No ': connected' frame within ${wait_seconds}s: the ingress is buffering /api/events" >&2
  exit 1
fi

echo "/api/events streamed its first frame within ${wait_seconds}s and stayed open"
