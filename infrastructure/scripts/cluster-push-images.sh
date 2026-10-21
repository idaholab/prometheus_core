#!/usr/bin/env bash
# Push the images Compose built (make build) to the k3d cluster's registry,
# under the names the Helm chart uses:
#
#   prometheus_platform-<service>  ->  localhost:5001/prometheus_<name>-devel:<tag>
#
# Then deploy them with
#   make cluster-deploy PROMETHEUS_IMAGE_REGISTRY=k3d-prometheus-registry.localhost:5001 PROMETHEUS_IMAGE_TAG=<tag>
#
# Images that weren't built (for example the debug agents without
# DEBUG_AGENTS=true) are skipped with a note.
#
# Usage: cluster-push-images.sh <compose-project> <tag>
set -euo pipefail

project="$1"
tag="$2"
registry=localhost:5001

# Compose service -> chart image name. frontend-prod is the prod target the
# chart runs; material-data-agent's service is called data-agent.
images=(
  "backend backend"
  "frontend-prod frontend"
  "client-agent client-agent"
  "synthesis-agent synthesis-agent"
  "form-filler-agent form-filler-agent"
  "artifact-debug-agent artifact-debug-agent"
  "code-render-debug-agent code-render-debug-agent"
  "corrosion-agent corrosion-agent"
  "data-agent data-agent"
  "radiation-agent radiation-agent"
  "thermal-agent thermal-agent"
  "thread-pattern-agent thread-pattern-agent"
  "osti-research-agent osti-research-agent"
)

for pair in "${images[@]}"; do
  read -r service name <<< "$pair"
  source="$project-$service"
  target="$registry/prometheus_$name-devel:$tag"
  if ! docker image inspect "$source" >/dev/null 2>&1; then
    echo "skip $source (not built)"
    continue
  fi
  docker tag "$source" "$target"
  docker push --quiet "$target"
done
