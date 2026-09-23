#!/bin/bash
set -euo pipefail
: "${SPIKE_ROOT:?use run.sh}"
cd "${SPIKE_ROOT}/sources/substrate"
run_log="${SPIKE_ROOT}/logs/launch-$(date -u +%Y%m%dT%H%M%SZ)-$1.log"
exec > >(tee "${run_log}") 2>&1
echo "AX spike phase $1, UTC $(date -u +%FT%TZ), context ${KUBECTL_CONTEXT}"
# Pinned image pulls/builds validate availability during the actual run.
[[ "$(docker info --format '{{.Architecture}}')" == aarch64 ]] || { echo "ARM64 Docker engine required" >&2; exit 1; }
case "$1" in
  create)
    # This is an explicit create-only script: existing spike resources are refused.
    exec /bin/bash hack/create-kind-cluster.sh
    ;;
  install|counter|check)
    [[ -f "${KUBECONFIG}" ]] || { echo "Missing spike kubeconfig" >&2; exit 1; }
    [[ "$(kubectl config current-context)" == "kind-autonomy-ax-spike" ]] || { echo "Unexpected spike context" >&2; exit 1; }
    if [[ "$1" == install ]]; then
      exec /bin/bash hack/install-ate-kind.sh --deploy-ate-system
    fi
    if [[ "$1" == check ]]; then
      exec "${SPIKE_ROOT}/../../.venv/bin/python" "${SPIKE_ROOT}/launch/counter_check.py"
    fi
    exec /bin/bash hack/install-ate-kind.sh --deploy-demo-counter
    ;;
  *) exit 2 ;;
esac
