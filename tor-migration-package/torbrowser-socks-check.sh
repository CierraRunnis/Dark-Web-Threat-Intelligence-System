#!/usr/bin/env bash
set -euo pipefail

host="${TOR_BROWSER_SOCKS_HOST:-127.0.0.1}"
port="${TOR_BROWSER_SOCKS_PORT:-9150}"

echo "Testing Tor Browser SOCKS at ${host}:${port}"
curl --socks5-hostname "${host}:${port}" -fsS https://check.torproject.org/api/ip
echo
