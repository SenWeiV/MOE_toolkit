#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${MOE_REMOTE_HOST:-${MOE_REMOTE_HOST}}"
REMOTE_ROOT="${MOE_REMOTE_ROOT:-/opt/moe-toolkit}"
REMOTE_SOURCE_DIR="${REMOTE_ROOT}/source"
REMOTE_DATA_DIR="${REMOTE_ROOT}/data"
REMOTE_RELEASES_DIR="${REMOTE_DATA_DIR}/releases"
REMOTE_ENV_FILE="${MOE_REMOTE_ENV_FILE:-${REMOTE_ROOT}/.env.prod}"
PUBLIC_BASE_URL="${MOE_PUBLIC_BASE_URL:-${MOE_PUBLIC_BASE_URL}}"
API_KEYS_RAW="${MOE_API_KEYS_RAW:-}"
API_KEY_STORE_PATH="${MOE_API_KEY_STORE_PATH:-/srv/moe/admin/api_keys.json}"
ADMIN_USERNAME="${MOE_ADMIN_USERNAME:-}"
ADMIN_PASSWORD="${MOE_ADMIN_PASSWORD:-}"
ADMIN_SESSION_SECRET="${MOE_ADMIN_SESSION_SECRET:-}"
LOCAL_RELEASE_ARCHIVE="${ROOT_DIR}/dist/moe-connector-macos.tar.gz"

if [[ -z "${API_KEYS_RAW}" ]]; then
  echo "MOE_API_KEYS_RAW is required." >&2
  exit 1
fi

if [[ -n "${ADMIN_USERNAME}${ADMIN_PASSWORD}${ADMIN_SESSION_SECRET}" ]]; then
  if [[ -z "${ADMIN_USERNAME}" || -z "${ADMIN_PASSWORD}" || -z "${ADMIN_SESSION_SECRET}" ]]; then
    echo "MOE_ADMIN_USERNAME, MOE_ADMIN_PASSWORD, and MOE_ADMIN_SESSION_SECRET must be set together." >&2
    exit 1
  fi
fi

bash "${ROOT_DIR}/scripts/build-connector-release.sh" >/dev/null

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_SOURCE_DIR}' '${REMOTE_DATA_DIR}' '${REMOTE_RELEASES_DIR}'"

rsync -avz --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.pytest_cache' \
  --exclude='__pycache__' \
  --exclude='.coverage' \
  --exclude='.state' \
  "${ROOT_DIR}/" \
  "${REMOTE_HOST}:${REMOTE_SOURCE_DIR}/"

rsync -avz \
  "${LOCAL_RELEASE_ARCHIVE}" \
  "${REMOTE_HOST}:${REMOTE_RELEASES_DIR}/"

ssh "${REMOTE_HOST}" "cat > '${REMOTE_ENV_FILE}' <<'EOF'
MOE_API_KEYS_RAW=${API_KEYS_RAW}
MOE_PUBLIC_BASE_URL=${PUBLIC_BASE_URL}
MOE_API_KEY_STORE_PATH=${API_KEY_STORE_PATH}
MOE_ADMIN_USERNAME=${ADMIN_USERNAME}
MOE_ADMIN_PASSWORD=${ADMIN_PASSWORD}
MOE_ADMIN_SESSION_SECRET=${ADMIN_SESSION_SECRET}
EOF
chmod 600 '${REMOTE_ENV_FILE}'
set -euo pipefail
cd '${REMOTE_SOURCE_DIR}'
bash scripts/build-tool-images.sh
docker compose --env-file '${REMOTE_ENV_FILE}' -f deploy/docker/compose.prod.yml up -d --build
docker compose --env-file '${REMOTE_ENV_FILE}' -f deploy/docker/compose.prod.yml ps
"

echo "Deployment completed on ${REMOTE_HOST}"
