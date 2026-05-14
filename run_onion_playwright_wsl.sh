#!/bin/bash
# Run onion crawler with Playwright in WSL through a healthchecked Tor SOCKS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR_ROOT="${SCRIPT_DIR}/darkweb_collector"

cd "$COLLECTOR_ROOT"

if [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

healthcheck="${COLLECTOR_ROOT}/scripts/tor_healthcheck.sh"
if [[ -x "$healthcheck" ]]; then
  if eval_output="$(bash "$healthcheck" --export)"; then
    eval "$eval_output"
  else
    echo "[run_onion_playwright_wsl] Tor healthcheck failed, falling back to 127.0.0.1:9150" >&2
    export TOR_SOCKS_HOST="${TOR_SOCKS_HOST:-127.0.0.1}"
    export TOR_SOCKS_PORT="${TOR_SOCKS_PORT:-9150}"
  fi
else
  export TOR_SOCKS_HOST="${TOR_SOCKS_HOST:-127.0.0.1}"
  export TOR_SOCKS_PORT="${TOR_SOCKS_PORT:-9150}"
fi

echo "Connecting to Tor: ${TOR_SOCKS_HOST}:${TOR_SOCKS_PORT} (layer=${TOR_SOCKS_LAYER:-unknown})"

target_url="${1:-http://hptqq2o2qjva7lcaaq67w36jihzivkaitkexorauw7b2yul2z6zozpqd.onion/}"
python scripts/fetch_onion_playwright.py "$target_url"
