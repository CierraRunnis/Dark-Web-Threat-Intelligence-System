#!/usr/bin/env bash
set -euo pipefail

host="${TOR_BROWSER_SOCKS_HOST:-127.0.0.1}"
port="${TOR_BROWSER_SOCKS_PORT:-9150}"
timeout="${TOR_BROWSER_CHECK_TIMEOUT:-25}"

echo "Testing Tor Browser SOCKS at ${host}:${port}"

targets=(
  "https://check.torproject.org/api/ip"
  "https://api.ipify.org?format=json"
  "https://httpbin.org/ip"
)

for target in "${targets[@]}"; do
  echo "Trying ${target}"
  if curl --http1.1 --socks5-hostname "${host}:${port}" -fsS -m "${timeout}" "${target}"; then
    echo
    exit 0
  fi
  echo "Request failed for ${target}" >&2
done

echo "SOCKS port is reachable, but Tor does not have a stable outbound circuit right now." >&2
echo "Check Tor Browser connection state, bridge status, and upstream proxy settings." >&2
exit 1
