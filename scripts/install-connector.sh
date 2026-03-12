#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-connector.sh [options]

Options:
  --server-url URL        Configure connector to use this cloud URL
  --api-key KEY           Configure connector with this API key
  --host HOST             Install host registration for claude-code, codex-cli, or openclaw (repeatable)
  --openclaw-workspace P  Target OpenClaw workspace path when --host openclaw is used
  --output-dir DIR        Output directory for downloaded artifacts
  --config-path PATH      Connector config path (default: ~/.moe-connector/config.toml)
  --python BIN            Python executable to use (default: python3)
  --force                 Recreate the runtime even if it already exists
  --skip-doctor           Skip post-install doctor check
  --help                  Show this help message
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
  PACKAGE_ROOT="${SCRIPT_DIR}"
elif [[ -f "${SCRIPT_DIR}/../pyproject.toml" ]]; then
  PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
  PACKAGE_ROOT="${SCRIPT_DIR}"
fi

LOCAL_ENV_HELPER="${PACKAGE_ROOT}/scripts/load-local-env.sh"
if [[ -f "${LOCAL_ENV_HELPER}" ]]; then
  # shellcheck source=scripts/load-local-env.sh
  . "${LOCAL_ENV_HELPER}"
fi

CONNECTOR_HOME="${HOME}/.moe-connector"
RUNTIME_DIR="${CONNECTOR_HOME}/runtime"
CONFIG_PATH="${CONNECTOR_HOME}/config.toml"
OUTPUT_DIR="${HOME}/MOE Outputs"
BIN_DIR="${HOME}/.local/bin"
COMMAND_SHIM="${BIN_DIR}/moe-connector"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVER_URL=""
API_KEY=""
DEFAULT_SERVER_URL="${MOE_PUBLIC_BASE_URL:-http://127.0.0.1:8080}"
SKIP_DOCTOR=0
FORCE_INSTALL=0
HOSTS=()
OPENCLAW_WORKSPACE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url)
      SERVER_URL="$2"
      shift 2
      ;;
    --api-key)
      API_KEY="$2"
      shift 2
      ;;
    --host)
      HOSTS+=("$2")
      shift 2
      ;;
    --openclaw-workspace)
      OPENCLAW_WORKSPACE="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --config-path)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --force)
      FORCE_INSTALL=1
      shift
      ;;
    --skip-doctor)
      SKIP_DOCTOR=1
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

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "${PYTHON_BIN} is required but was not found." >&2
  exit 1
fi

for host in "${HOSTS[@]}"; do
  if [[ "${host}" != "claude-code" && "${host}" != "codex-cli" && "${host}" != "openclaw" ]]; then
    echo "Unsupported host: ${host}" >&2
    exit 1
  fi
done

resolve_package_target() {
  local candidate
  for candidate in \
    "${PACKAGE_ROOT}/wheels"/moe_toolkit-*.whl \
    "${PACKAGE_ROOT}/dist/wheels"/moe_toolkit-*.whl
  do
    if [[ -f "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done

  if [[ -f "${PACKAGE_ROOT}/pyproject.toml" ]]; then
    echo "${PACKAGE_ROOT}"
    return 0
  fi

  echo "Unable to find a wheel or source tree for installation." >&2
  exit 1
}

PACKAGE_TARGET="$(resolve_package_target)"
CONFIG_DIR="$(dirname "${CONFIG_PATH}")"

mkdir -p "${CONNECTOR_HOME}" "${OUTPUT_DIR}" "${BIN_DIR}" "${CONFIG_DIR}"
if [[ ${FORCE_INSTALL} -eq 1 && -d "${RUNTIME_DIR}" ]]; then
  rm -rf "${RUNTIME_DIR}"
fi

"${PYTHON_BIN}" -m venv "${RUNTIME_DIR}"
. "${RUNTIME_DIR}/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install --no-cache-dir "${PACKAGE_TARGET}" >/dev/null

cat > "${COMMAND_SHIM}" <<EOF
#!/usr/bin/env bash
exec "${RUNTIME_DIR}/bin/moe-connector" "\$@"
EOF
chmod 755 "${COMMAND_SHIM}"

if [[ -n "${SERVER_URL}" || -n "${API_KEY}" ]]; then
  if [[ -z "${SERVER_URL}" || -z "${API_KEY}" ]]; then
    echo "--server-url and --api-key must be provided together." >&2
    exit 1
  fi
  "${COMMAND_SHIM}" configure \
    --server-url "${SERVER_URL}" \
    --api-key "${API_KEY}" \
    --output-dir "${OUTPUT_DIR}" \
    --config-path "${CONFIG_PATH}"
fi

for host in "${HOSTS[@]}"; do
  INSTALL_ARGS=(
    install
    --host "${host}"
    --command-path "${COMMAND_SHIM}"
    --config-path "${CONFIG_PATH}"
  )
  if [[ "${host}" == "openclaw" && -n "${OPENCLAW_WORKSPACE}" ]]; then
    INSTALL_ARGS+=(--workspace-path "${OPENCLAW_WORKSPACE}")
  fi
  "${COMMAND_SHIM}" "${INSTALL_ARGS[@]}"
done

if [[ ${SKIP_DOCTOR} -eq 0 && -f "${CONFIG_PATH}" ]]; then
  DOCTOR_ARGS=(doctor --config-path "${CONFIG_PATH}")
  for host in "${HOSTS[@]}"; do
    DOCTOR_ARGS+=(--host "${host}")
  done
  if [[ " ${HOSTS[*]} " == *" openclaw "* && -n "${OPENCLAW_WORKSPACE}" ]]; then
    DOCTOR_ARGS+=(--workspace-path "${OPENCLAW_WORKSPACE}")
  fi
  "${COMMAND_SHIM}" "${DOCTOR_ARGS[@]}"
fi

cat <<EOF
MOE Connector installed.

Runtime: ${RUNTIME_DIR}
Command: ${COMMAND_SHIM}
Config: ${CONFIG_PATH}
Output dir: ${OUTPUT_DIR}
Package source: ${PACKAGE_TARGET}
EOF

if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
  cat <<EOF

Warning: ${BIN_DIR} is not currently on your PATH.
Add this to your shell profile if you want to call moe-connector directly:
  export PATH="${BIN_DIR}:\$PATH"
EOF
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  cat <<EOF

Next steps:
  ${COMMAND_SHIM} configure --server-url ${DEFAULT_SERVER_URL} --api-key <YOUR_KEY>
  ${COMMAND_SHIM} install --host codex-cli --command-path ${COMMAND_SHIM} --config-path ${CONFIG_PATH}
  ${COMMAND_SHIM} doctor --config-path ${CONFIG_PATH}
EOF
fi
