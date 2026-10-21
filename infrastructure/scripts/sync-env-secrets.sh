#!/usr/bin/env bash
# Copy platform/.env into the two Secrets the Helm chart reads:
#
#   prometheus-env          every agent and the backend (envFrom)
#   prometheus-env-private  keys only some pods may see (secretKeyRef):
#                           the backend's signing and admin-plane keys and the
#                           database passwords
#
# Compose keeps the private keys off the agents too. Re-running updates both
# Secrets in place; values never pass through Helm.
#
# Usage: sync-env-secrets.sh <env-file> <kube-context> <namespace>
set -euo pipefail

env_file="$1"
context="$2"
namespace="$3"

private_keys="BACKEND_JWT_SECRET USER_IDENTITY_PRIVATE_KEY ADMIN_DB_ENCRYPTION_KEY ADMIN_DB_PASSWORD LITELLM_DB_PASSWORD"

shared="$(mktemp)"
private="$(mktemp)"
trap 'rm -f "$shared" "$private"' EXIT

# KEY=value lines only; comments and blanks are dropped. An empty value is
# skipped, so optional keys stay unset in the pod as they are in Compose.
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"
  [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || continue
  key="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"
  # Compose strips one pair of matching quotes; kubectl would keep them
  if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
    value="${BASH_REMATCH[1]}"
  fi
  [ -n "$value" ] || continue
  if [[ " $private_keys " == *" $key "* ]]; then
    printf '%s=%s\n' "$key" "$value" >> "$private"
  else
    printf '%s=%s\n' "$key" "$value" >> "$shared"
  fi
done < "$env_file"

apply() {
  kubectl --context "$context" -n "$namespace" create secret generic "$1" \
    --from-env-file="$2" --dry-run=client -o yaml \
    | kubectl --context "$context" -n "$namespace" apply -f -
}
apply prometheus-env "$shared"
apply prometheus-env-private "$private"
