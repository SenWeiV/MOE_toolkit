#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: uninstall-connector.sh [options]

Options:
  --host HOST        Remove host registration for claude-code or codex-cli (repeatable)
  --all-hosts        Remove registrations for both supported hosts
  --purge-config     Delete ~/.moe-connector/config.toml after uninstall
  --purge-output     Delete ~/MOE Outputs after uninstall
  --help             Show this help message
EOF
}

CONNECTOR_HOME="${HOME}/.moe-connector"
RUNTIME_DIR="${CONNECTOR_HOME}/runtime"
CONFIG_PATH="${CONNECTOR_HOME}/config.toml"
OUTPUT_DIR="${HOME}/MOE Outputs"
BIN_DIR="${HOME}/.local/bin"
COMMAND_SHIM="${BIN_DIR}/moe-connector"
PURGE_CONFIG=0
PURGE_OUTPUT=0
HOSTS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOSTS+=("$2")
      shift 2
      ;;
    --all-hosts)
      HOSTS=("codex-cli" "claude-code")
      shift
      ;;
    --purge-config)
      PURGE_CONFIG=1
      shift
      ;;
    --purge-output)
      PURGE_OUTPUT=1
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ${#HOSTS[@]} -eq 0 ]]; then
  HOSTS=("codex-cli" "claude-code")
fi

run_uninstall() {
  local connector_command
  connector_command=""
  if [[ -x "${COMMAND_SHIM}" ]]; then
    connector_command="${COMMAND_SHIM}"
  elif [[ -x "${RUNTIME_DIR}/bin/moe-connector" ]]; then
    connector_command="${RUNTIME_DIR}/bin/moe-connector"
  fi

  if [[ -n "${connector_command}" ]]; then
    for host in "${HOSTS[@]}"; do
      "${connector_command}" uninstall --host "${host}" >/dev/null || true
    done
  fi
}

run_uninstall

if [[ -f "${COMMAND_SHIM}" ]]; then
  rm -f "${COMMAND_SHIM}"
fi

if [[ -d "${RUNTIME_DIR}" ]]; then
  rm -rf "${RUNTIME_DIR}"
fi

if [[ ${PURGE_CONFIG} -eq 1 && -f "${CONFIG_PATH}" ]]; then
  rm -f "${CONFIG_PATH}"
fi

if [[ ${PURGE_OUTPUT} -eq 1 && -d "${OUTPUT_DIR}" ]]; then
  rm -rf "${OUTPUT_DIR}"
fi

cat <<EOF
MOE Connector removed.

Removed runtime: ${RUNTIME_DIR}
Removed shim: ${COMMAND_SHIM}
Host registrations processed: ${HOSTS[*]}
Config kept: $([[ ${PURGE_CONFIG} -eq 1 ]] && echo no || echo yes)
Output dir kept: $([[ ${PURGE_OUTPUT} -eq 1 ]] && echo no || echo yes)
EOF
