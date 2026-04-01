#!/usr/bin/env bash

# Import Windows proxy settings into WSL shells.
# Prefer an explicit local Clash/Mihomo port if reachable from WSL.

_wsl_proxy_gateway="$(ip route 2>/dev/null | awk '/^default/ {print $3; exit}')"
_wsl_proxy_host="${_wsl_proxy_gateway:-172.26.0.1}"
_wsl_proxy_port="${WSL_PROXY_PORT:-7892}"

_wsl_probe_port() {
  timeout 1 bash -lc "</dev/tcp/${_wsl_proxy_host}/${1}" >/dev/null 2>&1
}

if ! _wsl_probe_port "${_wsl_proxy_port}"; then
  for _candidate in 7892 7890 7897; do
    if _wsl_probe_port "${_candidate}"; then
      _wsl_proxy_port="${_candidate}"
      break
    fi
  done
fi

if _wsl_probe_port "${_wsl_proxy_port}"; then
  export WSL_PROXY_HOST="${_wsl_proxy_host}"
  export WSL_PROXY_PORT="${_wsl_proxy_port}"
  export http_proxy="http://${_wsl_proxy_host}:${_wsl_proxy_port}"
  export https_proxy="http://${_wsl_proxy_host}:${_wsl_proxy_port}"
  export HTTP_PROXY="${http_proxy}"
  export HTTPS_PROXY="${https_proxy}"
  export all_proxy="socks5://${_wsl_proxy_host}:${_wsl_proxy_port}"
  export ALL_PROXY="${all_proxy}"
  export no_proxy="127.0.0.1,localhost,::1"
  export NO_PROXY="${no_proxy}"
fi

unset _wsl_proxy_gateway
unset _wsl_proxy_host
unset _wsl_proxy_port
unset _candidate

