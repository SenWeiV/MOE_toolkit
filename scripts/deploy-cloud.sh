#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/load-local-env.sh
. "${ROOT_DIR}/scripts/load-local-env.sh"

REMOTE_HOST="${MOE_REMOTE_HOST:-deploy@127.0.0.1}"
REMOTE_ROOT="${MOE_REMOTE_ROOT:-/opt/moe-toolkit}"
REMOTE_SOURCE_DIR="${REMOTE_ROOT}/source"
REMOTE_DATA_DIR="${REMOTE_ROOT}/data"
REMOTE_RELEASES_DIR="${REMOTE_DATA_DIR}/releases"
REMOTE_ENV_FILE="${MOE_REMOTE_ENV_FILE:-${REMOTE_ROOT}/.env.prod}"
DEFAULT_PUBLIC_BASE_URL="http://127.0.0.1:8080"
DEFAULT_API_KEY_STORE_PATH="/srv/moe/admin/api_keys.json"
LOCAL_PUBLIC_BASE_URL="${MOE_PUBLIC_BASE_URL:-}"
LOCAL_API_KEYS_RAW="${MOE_API_KEYS_RAW:-}"
LOCAL_API_KEY_STORE_PATH="${MOE_API_KEY_STORE_PATH:-}"
LOCAL_ADMIN_USERNAME="${MOE_ADMIN_USERNAME:-}"
LOCAL_ADMIN_PASSWORD="${MOE_ADMIN_PASSWORD:-}"
LOCAL_ADMIN_SESSION_SECRET="${MOE_ADMIN_SESSION_SECRET:-}"
LOCAL_RELEASE_ARCHIVE="${ROOT_DIR}/dist/moe-connector-macos.tar.gz"

read_remote_env_json() {
  ssh "${REMOTE_HOST}" "REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ['REMOTE_ENV_FILE'])
tracked = {
    'MOE_API_KEYS_RAW': '',
    'MOE_PUBLIC_BASE_URL': '',
    'MOE_API_KEY_STORE_PATH': '',
    'MOE_ADMIN_USERNAME': '',
    'MOE_ADMIN_PASSWORD': '',
    'MOE_ADMIN_SESSION_SECRET': '',
}
if path.exists():
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in tracked:
            tracked[key] = value
print(json.dumps(tracked, ensure_ascii=True))
PY"
}

REMOTE_ENV_JSON="$(read_remote_env_json)"

read_json_value() {
  local key="$1"
  python3 - "${REMOTE_ENV_JSON}" "${key}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload.get(sys.argv[2], ""))
PY
}

REMOTE_API_KEYS_RAW="$(read_json_value MOE_API_KEYS_RAW)"
REMOTE_PUBLIC_BASE_URL="$(read_json_value MOE_PUBLIC_BASE_URL)"
REMOTE_API_KEY_STORE_PATH="$(read_json_value MOE_API_KEY_STORE_PATH)"
REMOTE_ADMIN_USERNAME="$(read_json_value MOE_ADMIN_USERNAME)"
REMOTE_ADMIN_PASSWORD="$(read_json_value MOE_ADMIN_PASSWORD)"
REMOTE_ADMIN_SESSION_SECRET="$(read_json_value MOE_ADMIN_SESSION_SECRET)"

API_KEYS_RAW="${LOCAL_API_KEYS_RAW:-${REMOTE_API_KEYS_RAW}}"
PUBLIC_BASE_URL="${LOCAL_PUBLIC_BASE_URL:-${REMOTE_PUBLIC_BASE_URL:-${DEFAULT_PUBLIC_BASE_URL}}}"
API_KEY_STORE_PATH="${LOCAL_API_KEY_STORE_PATH:-${REMOTE_API_KEY_STORE_PATH:-${DEFAULT_API_KEY_STORE_PATH}}}"

if [[ -n "${LOCAL_ADMIN_USERNAME}${LOCAL_ADMIN_PASSWORD}${LOCAL_ADMIN_SESSION_SECRET}" ]]; then
  if [[ -z "${LOCAL_ADMIN_USERNAME}" || -z "${LOCAL_ADMIN_PASSWORD}" || -z "${LOCAL_ADMIN_SESSION_SECRET}" ]]; then
    echo "MOE_ADMIN_USERNAME, MOE_ADMIN_PASSWORD, and MOE_ADMIN_SESSION_SECRET must be set together." >&2
    exit 1
  fi
  ADMIN_USERNAME="${LOCAL_ADMIN_USERNAME}"
  ADMIN_PASSWORD="${LOCAL_ADMIN_PASSWORD}"
  ADMIN_SESSION_SECRET="${LOCAL_ADMIN_SESSION_SECRET}"
else
  ADMIN_USERNAME="${REMOTE_ADMIN_USERNAME}"
  ADMIN_PASSWORD="${REMOTE_ADMIN_PASSWORD}"
  ADMIN_SESSION_SECRET="${REMOTE_ADMIN_SESSION_SECRET}"
fi

if [[ -z "${API_KEYS_RAW}" ]]; then
  echo "MOE_API_KEYS_RAW is missing locally and on the remote server." >&2
  exit 1
fi

if [[ -n "${ADMIN_USERNAME}${ADMIN_PASSWORD}${ADMIN_SESSION_SECRET}" ]]; then
  if [[ -z "${ADMIN_USERNAME}" || -z "${ADMIN_PASSWORD}" || -z "${ADMIN_SESSION_SECRET}" ]]; then
    echo "Resolved admin credentials are incomplete. Fix the remote .env.prod or provide all three local values." >&2
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
