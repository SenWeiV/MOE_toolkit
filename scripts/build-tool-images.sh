#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for tool_dir in "${ROOT_DIR}"/tools/curated/*; do
  if [[ ! -f "${tool_dir}/Dockerfile" ]]; then
    continue
  fi
  tool_name="$(basename "${tool_dir}")"
  image_name="moe-tool-${tool_name}"
  docker build -t "${image_name}" "${tool_dir}"
done

echo "Built curated MOE tool images"
