#!/usr/bin/env bash
# Check the stack deployed to the k3d cluster from the host, the way make up
# checks Compose: platform/scripts/check_platform.py against the backend's
# /healthz, the frontend and its /api route through the ingress on
# localhost:8080, and every deployed agent registered with LiteLLM.
#
# helm --wait already covers the pods' own probes; this covers what they can't
# see: the ingress, and LiteLLM registration, which retries in the background
# while an agent keeps serving.
#
# The backend and LiteLLM aren't exposed outside the cluster, so they're
# reached through kubectl port-forward on free local ports.
#
# Usage: cluster-check.sh <kube-context> <namespace> <timeout-seconds> <agent-dir>...
set -euo pipefail

context="$1"
namespace="$2"
timeout="$3"
shift 3

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
platform="$(cd "$here/../../platform" && pwd)"

free_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' EXIT
forward() {
  kubectl --context "$context" -n "$namespace" port-forward "svc/$1" "$2:$3" >/dev/null &
  pids+=("$!")
}

backend_port="$(free_port)"
litellm_port="$(free_port)"
forward backend "$backend_port" 8000
forward litellm "$litellm_port" 4000

# Every agent the release runs: the deployments with an agent card in the repo
deployed="$(kubectl --context "$context" -n "$namespace" get deploy -o jsonpath='{.items[*].metadata.name}')"
agent_dirs=()
for dir in "$@"; do
  name="$(basename "$dir")"
  # material-data-agent deploys as data-agent, its compose service name
  [ "$name" = material-data-agent ] && name=data-agent
  [[ " $deployed " == *" $name "* ]] && agent_dirs+=("$dir")
done

# check_platform.py reads LITELLM_MASTER_KEY from platform/.env, the same
# file make cluster-deploy copied into the cluster
python3 -u "$platform/scripts/check_platform.py" --timeout "$timeout" \
  --backend-port "$backend_port" --litellm-port "$litellm_port" --frontend-port 8080 \
  "${agent_dirs[@]}"
