#!/usr/bin/env bash
set -euo pipefail

SNOWFLAKE_GO_PACKAGE="${SNOWFLAKE_GO_PACKAGE:-gitlab.torproject.org/tpo/anti-censorship/pluggable-transports/snowflake/v2/client@latest}"

bridge_info() {
  echo "[INFO] $*"
}

bridge_warn() {
  echo "[WARN] $*" >&2
}

bridge_run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  bridge_warn "sudo is unavailable; cannot install Tor bridge runtime packages"
  return 1
}

bridge_repair_yarn_repository() {
  local yarn_list="/etc/apt/sources.list.d/yarn.list"
  [[ -f "$yarn_list" ]] || return 1
  command -v curl >/dev/null 2>&1 || return 1

  bridge_info "repairing Yarn apt repository signing key"
  bridge_run_as_root install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://dl.yarnpkg.com/debian/pubkey.gpg |
    bridge_run_as_root tee /etc/apt/keyrings/yarn.asc >/dev/null
  bridge_run_as_root chmod 0644 /etc/apt/keyrings/yarn.asc
  printf '%s\n' "deb [signed-by=/etc/apt/keyrings/yarn.asc] https://dl.yarnpkg.com/debian/ stable main" |
    bridge_run_as_root tee "$yarn_list" >/dev/null
}

bridge_apt_get_update() {
  local update_log
  update_log="$(mktemp)"
  if bridge_run_as_root apt-get update 2>&1 | tee "$update_log"; then
    rm -f "$update_log"
    return 0
  fi

  if grep -Eq "dl.yarnpkg.com|NO_PUBKEY 62D54FD4003F6525|yarn" "$update_log" &&
    bridge_repair_yarn_repository; then
    rm -f "$update_log"
    bridge_run_as_root apt-get update
    return
  fi

  cat "$update_log" >&2
  rm -f "$update_log"
  return 1
}

bridge_apt_package_available() {
  local package_name="$1"
  apt-cache show "$package_name" >/dev/null 2>&1
}

bridge_install_packages() {
  local packages=("$@")
  (( ${#packages[@]} > 0 )) || return 0
  bridge_apt_get_update
  bridge_info "installing Tor bridge package(s): ${packages[*]}"
  bridge_run_as_root apt-get install -y "${packages[@]}"
}

bridge_ensure_go() {
  if command -v go >/dev/null 2>&1; then
    return 0
  fi
  bridge_install_packages golang-go
  command -v go >/dev/null 2>&1
}

bridge_install_snowflake_from_go() {
  local tmp_bin built_binary
  bridge_ensure_go || return 1

  tmp_bin="$(mktemp -d)"
  bridge_info "building snowflake-client from ${SNOWFLAKE_GO_PACKAGE}"
  if ! GOBIN="$tmp_bin" go install "$SNOWFLAKE_GO_PACKAGE"; then
    rm -rf "$tmp_bin"
    return 1
  fi

  built_binary="$tmp_bin/client"
  if [[ ! -x "$built_binary" ]]; then
    built_binary="$tmp_bin/snowflake-client"
  fi
  if [[ ! -x "$built_binary" ]]; then
    rm -rf "$tmp_bin"
    bridge_warn "go install completed but no Snowflake client binary was produced"
    return 1
  fi

  bridge_run_as_root install -m 0755 "$built_binary" /usr/local/bin/snowflake-client
  rm -rf "$tmp_bin"
  command -v snowflake-client >/dev/null 2>&1
}

bridge_ensure_snowflake_transport() {
  if command -v snowflake-client >/dev/null 2>&1 || command -v lyrebird >/dev/null 2>&1; then
    return 0
  fi

  local transport_package
  for transport_package in snowflake-client lyrebird; do
    if bridge_apt_package_available "$transport_package"; then
      bridge_install_packages "$transport_package"
      if command -v snowflake-client >/dev/null 2>&1 || command -v lyrebird >/dev/null 2>&1; then
        return 0
      fi
    fi
  done

  bridge_install_snowflake_from_go
}

install_tor_bridge_runtime() {
  if ! command -v apt-get >/dev/null 2>&1; then
    bridge_warn "apt-get is unavailable; skipping automatic Tor bridge runtime install"
    return 1
  fi

  local packages=()
  command -v curl >/dev/null 2>&1 || packages+=("curl")
  command -v tor >/dev/null 2>&1 || packages+=("tor")
  command -v obfs4proxy >/dev/null 2>&1 || packages+=("obfs4proxy")
  if (( ${#packages[@]} > 0 )); then
    bridge_install_packages "${packages[@]}"
  fi

  if ! bridge_ensure_snowflake_transport; then
    bridge_warn "Snowflake transport is unavailable. Install snowflake-client or lyrebird, or set DARKWEB_TOR_TRANSPORT_EXECUTABLE."
    return 1
  fi

  bridge_info "Tor bridge runtime:"
  command -v tor || true
  command -v snowflake-client || command -v lyrebird || true
  command -v obfs4proxy || true
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  install_tor_bridge_runtime "$@"
fi
