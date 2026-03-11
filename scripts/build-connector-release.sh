#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
WHEELS_DIR="${DIST_DIR}/wheels"
RELEASE_DIR="${DIST_DIR}/moe-connector-release"
ARCHIVE_PATH="${DIST_DIR}/moe-connector-macos.tar.gz"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "${PYTHON_BIN} is required but was not found." >&2
  exit 1
fi

mkdir -p "${WHEELS_DIR}"
rm -rf "${RELEASE_DIR}"
mkdir -p "${RELEASE_DIR}/wheels"

"${PYTHON_BIN}" -m pip wheel --no-deps "${ROOT_DIR}" --wheel-dir "${WHEELS_DIR}" >/dev/null

latest_wheel="$(ls -1t "${WHEELS_DIR}"/moe_toolkit-*.whl | head -1)"
if [[ -z "${latest_wheel}" ]]; then
  echo "No wheel was produced." >&2
  exit 1
fi

cp "${latest_wheel}" "${RELEASE_DIR}/wheels/"
cp "${ROOT_DIR}/scripts/install-connector.sh" "${RELEASE_DIR}/install.sh"
cp "${ROOT_DIR}/scripts/uninstall-connector.sh" "${RELEASE_DIR}/uninstall.sh"
cp "${ROOT_DIR}/README.md" "${RELEASE_DIR}/README.md"

LC_ALL=C tar -C "${DIST_DIR}" -czf "${ARCHIVE_PATH}" "$(basename "${RELEASE_DIR}")"

cat <<EOF
Connector release package created.

Release dir: ${RELEASE_DIR}
Archive: ${ARCHIVE_PATH}
Wheel: $(basename "${latest_wheel}")

Users can unpack the archive and run:
  bash install.sh --server-url ${MOE_PUBLIC_BASE_URL} --api-key <YOUR_KEY> --host codex-cli
EOF
