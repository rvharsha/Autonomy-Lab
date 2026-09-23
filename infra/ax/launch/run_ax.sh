#!/bin/bash
# Scoped launch entry point; all provider credentials are excluded.
set -euo pipefail
SPIKE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(cd "${SPIKE_ROOT}/../.." && pwd)"
if [[ $# != 1 || ! "$1" =~ ^(create|install|counter|ax_install|ax_check|ax_integration)$ ]]; then
  echo "Usage: bash .state/ax-spike/launch/run.sh {create|install|counter|check}" >&2
  exit 2
fi
umask 077
mkdir -p "${SPIKE_ROOT}/runtime/docker-config" "${SPIKE_ROOT}/runtime/config" "${SPIKE_ROOT}/tmp" \
  "${SPIKE_ROOT}/cache/go-build" "${SPIKE_ROOT}/cache/go-mod" "${SPIKE_ROOT}/cache/gopath"
docker_endpoint="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}"
exec /usr/bin/env -i \
  PATH="${SPIKE_ROOT}/tools/go/bin:${SPIKE_ROOT}/tools/ko:${SPIKE_ROOT}/tools/bin:${PROJECT_ROOT}/.tools:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  SPIKE_ROOT="${SPIKE_ROOT}" AX_LAB_INTEGRATION_ENV_FILE="${AX_LAB_INTEGRATION_ENV_FILE:-}" \
  TMPDIR="${SPIKE_ROOT}/tmp" XDG_CONFIG_HOME="${SPIKE_ROOT}/runtime/config" \
  DOCKER_HOST="${docker_endpoint}" DOCKER_CONFIG="${SPIKE_ROOT}/runtime/docker-config" \
  KUBECONFIG="${SPIKE_ROOT}/runtime/kubeconfig" KUBECTL_CONTEXT="kind-autonomy-ax-spike" \
  KIND_CLUSTER_NAME="autonomy-ax-spike" KIND_REGISTRY_NAME="autonomy-ax-spike-registry" KIND_REGISTRY_PORT="5007" \
  KIND_NODE_IMAGE="kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed" IP_FAMILY="ipv4" \
  KO_DOCKER_REPO="localhost:5007" KO_DEFAULTPLATFORMS="linux/arm64" \
  GOENV="off" GOTOOLCHAIN="local" GOMAXPROCS="2" GOFLAGS="-p=2" CGO_ENABLED="0" \
  GOCACHE="${SPIKE_ROOT}/cache/go-build" GOMODCACHE="${SPIKE_ROOT}/cache/go-mod" GOPATH="${SPIKE_ROOT}/cache/gopath" \
  GOPROXY="https://proxy.golang.org" GOSUMDB="sum.golang.org" \
  GIT_CONFIG_GLOBAL="/dev/null" GIT_CONFIG_NOSYSTEM="1" GIT_TERMINAL_PROMPT="0" \
  NO_DEV_ENV="true" ATE_API_POSTGRES_CLOUDSQL_INSTANCE="" \
  /bin/bash "${SPIKE_ROOT}/launch/phase_ax.sh" "$1"
