#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get is unavailable; skipping Tor bridge runtime install"
  exit 0
fi

sudo apt-get update
sudo apt-get install -y tor snowflake-client obfs4proxy python3-venv xvfb x11vnc openbox

tor --version | head -1
command -v snowflake-client
command -v obfs4proxy

if command -v python3 >/dev/null 2>&1; then
  tmp_venv="$(mktemp -d)"
  python3 -m venv "$tmp_venv/venv"
  "$tmp_venv/venv/bin/python" -m pip install --upgrade pip >/dev/null
  "$tmp_venv/venv/bin/python" -m pip install playwright >/dev/null
  "$tmp_venv/venv/bin/python" -m playwright install-deps chromium firefox
  rm -rf "$tmp_venv"
fi
