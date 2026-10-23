#!/usr/bin/env bash
# Check the tools needed to run Prometheus locally.
#
#   check-local-prereqs.sh --compose   Docker only (the Docker Compose stack)
#   check-local-prereqs.sh --cluster   Docker, k3d, kubectl, helm and tilt (the k3d cluster)
#
# Reports every problem, not just the first, and exits non-zero if any tool is
# missing, too old, or (for Docker) not running. SKIP_PREREQUISITES=1 skips it.
set -uo pipefail

mode="${1:---compose}"
case "$mode" in
  --compose | --cluster) ;;
  *)
    echo "usage: $0 [--compose|--cluster]" >&2
    exit 2
    ;;
esac

if [ "${SKIP_PREREQUISITES:-}" = "1" ]; then
  exit 0
fi

MIN_DOCKER=24.0
MIN_K3D=5.7.0
MIN_KUBECTL=1.36.0
MIN_HELM=3.14.0
MIN_TILT=0.37.0

status=0

# version_ge A B: true if version A >= version B.
version_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# First x.y[.z] in the input, without a leading "v".
extract_version() {
  grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1
}

error() {
  printf "  [ERROR] %s\n" "$1"
  shift
  for line in "$@"; do
    printf "          %s\n" "$line"
  done
  status=1
}

# check_tool NAME MINIMUM VERSION_CMD INSTALL_HINT
check_tool() {
  local name="$1" min="$2" version_cmd="$3" hint="$4" version
  if ! command -v "$name" >/dev/null 2>&1; then
    error "The $name command is not available." "Install it: $hint"
    return
  fi
  version="$(eval "$version_cmd" 2>/dev/null | extract_version)"
  if [ -z "$version" ]; then
    error "Could not determine the $name version." "Need $min or newer. Install: $hint"
  elif ! version_ge "$version" "$min"; then
    error "$name $version is too old; need $min or newer." "Upgrade: $hint"
  else
    printf "  [OK] %s %s\n" "$name" "$version"
  fi
}

check_docker() {
  local version
  if ! command -v docker >/dev/null 2>&1; then
    error "The docker command is not available." \
      "Install Docker and ensure it is available on PATH."
  elif ! docker info >/dev/null 2>&1; then
    error "Docker is installed, but the Docker daemon is unavailable." \
      "Start Docker, then verify access by running 'docker info'." \
      "Also check your Docker socket permissions if needed."
  else
    version="$(docker version --format '{{.Server.Version}}' 2>/dev/null | extract_version)"
    if [ -n "$version" ] && ! version_ge "$version" "$MIN_DOCKER"; then
      error "Docker $version is too old; need $MIN_DOCKER or newer."
    else
      printf "  [OK] Docker is running.\n"
    fi
  fi
}

printf "\nChecking prerequisites...\n"

check_docker

if [ "$mode" = "--cluster" ]; then
  check_tool k3d "$MIN_K3D" "k3d version" \
    "curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash"
  check_tool kubectl "$MIN_KUBECTL" "kubectl version --client" \
    "https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/"
  check_tool helm "$MIN_HELM" "helm version --template '{{.Version}}'" \
    "https://helm.sh/docs/intro/install/"
  check_tool tilt "$MIN_TILT" "tilt version" \
    "curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash"
  if [ "$status" -ne 0 ]; then
    printf "\n  On macOS (not yet verified): brew install k3d kubectl helm tilt\n"
  fi
fi

if [ "$status" -ne 0 ]; then
  printf "\nPrerequisite check failed. Resolve the errors above and try again.\n\n"
  exit "$status"
fi
printf "All prerequisites are available.\n\n"
