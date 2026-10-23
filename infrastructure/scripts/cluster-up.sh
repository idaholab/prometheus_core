#!/usr/bin/env bash
# Create the local k3d cluster "prometheus" if it does not already exist, or
# start it if it exists but is stopped.
#
# Adds what k3d-config.yaml cannot express: the INL root CA (downloaded, then
# mounted with an absolute host path) and proxy settings taken from the host
# environment, only when they are set.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
cluster=prometheus
ca_url="https://certstore.inl.gov/pki/CAINLROOT_B64.crt"
ca_dir="${XDG_CACHE_HOME:-$HOME/.cache}/prometheus"
ca="$ca_dir/CAINLROOT_B64.crt"

if k3d cluster get "$cluster" >/dev/null 2>&1; then
  servers="$(k3d cluster get "$cluster" --no-headers | awk '{print $2}')"
  if [ "${servers%%/*}" = "${servers##*/}" ]; then
    echo "Cluster '$cluster' is already running; nothing to do."
  else
    k3d cluster start "$cluster"
  fi
  exit 0
fi

# The INL root CA lets containerd in the node pull k3s's system images through
# INL's TLS inspection. Off the INL network the download fails and is not needed.
mkdir -p "$ca_dir"
tmp="$(mktemp)"
if curl -fsSL --max-time 15 -o "$tmp" "$ca_url" && grep -q 'BEGIN CERTIFICATE' "$tmp"; then
  mv "$tmp" "$ca"
else
  rm -f "$tmp"
  if [ -f "$ca" ]; then
    echo "[WARN] Could not download the INL CA; using the cached copy at $ca" >&2
  else
    echo "[WARN] Could not download the INL CA from $ca_url; continuing without it (fine off the INL network)" >&2
  fi
fi

args=(--config "$root/infrastructure/local/k3d-config.yaml")
# containerd trusts every certificate in /etc/ssl/certs. Mounted from a stable
# path because the node keeps referring to it across restarts.
[ -f "$ca" ] && args+=(--volume "$ca:/etc/ssl/certs/CAINLROOT_B64.crt@server:*")

# In-cluster traffic must never go through the proxy.
cluster_no_proxy="localhost,127.0.0.1,.svc,.cluster.local,10.42.0.0/16,10.43.0.0/16,k3d-prometheus-registry.localhost"
proxy_set=false
for var in HTTP_PROXY HTTPS_PROXY; do
  value="${!var:-}"
  [ -z "$value" ] && value="$(printenv "${var,,}" || true)"
  if [ -n "$value" ]; then
    args+=(--env "$var=$value@server:*")
    proxy_set=true
  fi
done
if [ "$proxy_set" = true ]; then
  no_proxy="${NO_PROXY:-${no_proxy:-}}"
  args+=(--env "NO_PROXY=${no_proxy:+$no_proxy,}$cluster_no_proxy@server:*")
fi

k3d cluster create "${args[@]}"

echo
echo "Cluster '$cluster' is up."
echo "  Push images:  docker push localhost:5001/<name>:<tag>"
echo "  Pod images:   k3d-prometheus-registry.localhost:5001/<name>:<tag>"
echo "  Ingress:      http://localhost:8080"
