#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get is unavailable; skipping Tor bridge runtime install"
  exit 0
fi

sudo apt-get update
sudo apt-get install -y tor snowflake-client obfs4proxy

tor --version | head -1
command -v snowflake-client
command -v obfs4proxy
