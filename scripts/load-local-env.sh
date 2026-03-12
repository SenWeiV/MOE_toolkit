#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_local_env_defaults() {
  local env_file="${ROOT_DIR}/.env.local"
  local raw_line=""
  local line=""
  local key=""
  local value=""

  [[ -f "${env_file}" ]] || return 0

  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "${line}" || "${line}" == \#* || "${line}" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"

    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    [[ -n "${!key+x}" ]] && continue
    export "${key}=${value}"
  done < "${env_file}"
}

load_local_env_defaults
