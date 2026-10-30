#!/usr/bin/env bash
set -euo pipefail

if [[ -f "$(pwd)/scripts/generate_fixture_marts.py" ]]; then
  REPO_ROOT="$(pwd)"
elif [[ -f "/app/applet/scripts/generate_fixture_marts.py" ]]; then
  REPO_ROOT="/app/applet"
else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

if [[ "${1:-}" == "--setup" ]]; then
  cp -f "${REPO_ROOT}/scripts/uv_shim.sh" /usr/local/bin/uv
  chmod +x /usr/local/bin/uv
  python3 "${REPO_ROOT}/scripts/generate_fixture_marts.py" --build-only
  if [[ ! -x "${REPO_ROOT}/site/node_modules/.bin/observable" ]]; then
    npm --prefix "${REPO_ROOT}/site" install --no-audit --no-fund
  fi
  if [[ -f "${REPO_ROOT}/site/node_modules/.bin/observable" ]]; then
    ln -sf "${REPO_ROOT}/site/node_modules/.bin/observable" /usr/local/bin/observable || true
  fi
  PREVIEW_JS="${REPO_ROOT}/site/node_modules/@observablehq/framework/dist/client/preview.js"
  if [[ -f "${PREVIEW_JS}" ]]; then
    sed -i 's/protocol: location.protocol === "https:" ? "wss" : "ws"[[:space:]]*}[[:space:]]*)/protocol: location.protocol === "https:" ? "wss" : "ws" }).href/g' "${PREVIEW_JS}" || true
  fi
  exit 0
fi

# Intercept: uv run python -m pipeline.site_data [--parquet] <name>
if [[ "${1:-}" == "run" && "${2:-}" == "python" && "${3:-}" == "-m" && "${4:-}" == "pipeline.site_data" ]]; then
  shift 4
  exec python3 "${REPO_ROOT}/scripts/generate_fixture_marts.py" "$@"
fi

shift || true
exec "$@"
