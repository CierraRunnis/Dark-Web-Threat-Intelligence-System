#!/usr/bin/env bash

# Source this in WSL to route CLI traffic through the Windows Tor Browser SOCKS proxy.

export TOR_BROWSER_SOCKS_HOST="${TOR_BROWSER_SOCKS_HOST:-127.0.0.1}"
export TOR_BROWSER_SOCKS_PORT="${TOR_BROWSER_SOCKS_PORT:-9150}"
export ALL_PROXY="socks5://${TOR_BROWSER_SOCKS_HOST}:${TOR_BROWSER_SOCKS_PORT}"
export all_proxy="${ALL_PROXY}"
export NO_PROXY="127.0.0.1,localhost,::1"
export no_proxy="${NO_PROXY}"
