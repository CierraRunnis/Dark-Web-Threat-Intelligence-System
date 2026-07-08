#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOR_INSTALLER="$PROJECT_ROOT/darkweb_collector/scripts/install_tor_bridge_runtime.sh"

if [[ -x "$TOR_INSTALLER" || -f "$TOR_INSTALLER" ]]; then
  bash "$TOR_INSTALLER"
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y tor obfs4proxy
else
  echo "apt-get is unavailable; skipping Tor bridge runtime install"
  exit 0
fi

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get install -y python3-venv xvfb x11vnc openbox
fi

if command -v python3 >/dev/null 2>&1; then
  tmp_venv="$(mktemp -d)"
  python3 -m venv "$tmp_venv/venv"
  "$tmp_venv/venv/bin/python" -m pip install --upgrade pip >/dev/null
  "$tmp_venv/venv/bin/python" -m pip install playwright >/dev/null
  "$tmp_venv/venv/bin/python" -m playwright install-deps chromium firefox
  rm -rf "$tmp_venv"
fi
