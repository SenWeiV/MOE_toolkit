#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker build -t moe-tool-pandas "${ROOT_DIR}/tools/curated/pandas"
docker build -t moe-tool-matplotlib "${ROOT_DIR}/tools/curated/matplotlib"

echo "Built moe-tool-pandas and moe-tool-matplotlib"
