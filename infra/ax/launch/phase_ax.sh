#!/bin/bash
set -euo pipefail
: "${SPIKE_ROOT:?use run_ax.sh}"
case "$1" in
  create|install|counter) exec /bin/bash "${SPIKE_ROOT}/launch/phase.sh" "$1" ;;
  ax_install|ax_check|ax_integration) exec "${SPIKE_ROOT}/../../.venv/bin/python" "${SPIKE_ROOT}/launch/$1.py" ;;
  *) exit 2 ;;
esac
