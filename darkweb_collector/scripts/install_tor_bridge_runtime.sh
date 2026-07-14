#!/usr/bin/env bash
set -euo pipefail

SNOWFLAKE_GO_PACKAGE="${SNOWFLAKE_GO_PACKAGE:-gitlab.torproject.org/tpo/anti-censorship/pluggable-transports/snowflake/v2/client@latest}"
TOR_RELEASE_METADATA_URL="${TOR_RELEASE_METADATA_URL:-https://aus1.torproject.org/torbrowser/update_3/release/downloads.json}"
TOR_DIST_BASE_URL="${TOR_DIST_BASE_URL:-https://dist.torproject.org/torbrowser}"
TOR_EXPERT_ROOT="${DARKWEB_TOR_EXPERT_DIR:-$HOME/.local/share/darkweb-threat-intel/tor-expert}"

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

bridge_expert_architecture() {
  case "$(uname -m)" in
    x86_64 | amd64) printf '%s\n' "x86_64" ;;
    aarch64 | arm64) printf '%s\n' "aarch64" ;;
    *) return 1 ;;
  esac
}

bridge_latest_tor_version() {
  local metadata
  if [[ -n "${TOR_EXPERT_BUNDLE_VERSION:-}" ]]; then
    printf '%s\n' "$TOR_EXPERT_BUNDLE_VERSION"
    return
  fi
  metadata="$(curl -fsSL "$TOR_RELEASE_METADATA_URL")" || return 1
  printf '%s' "$metadata" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["version"])' 2>/dev/null
}

bridge_configure_expert_runtime() {
  local runtime_root="$1"
  local wrapper="$HOME/.local/bin/darkweb-tor"
  [[ -x "$runtime_root/tor/tor" && -x "$runtime_root/tor/pluggable_transports/lyrebird" ]] || return 1

  mkdir -p "$(dirname "$wrapper")"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'runtime_dir=%q\n' "$runtime_root/tor"
    printf '%s\n' 'export LD_LIBRARY_PATH="$runtime_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"'
    printf '%s\n' 'exec "$runtime_dir/tor" "$@"'
  } >"$wrapper"
  chmod 0755 "$wrapper"

  export PATH="$HOME/.local/bin:$PATH"
  export DARKWEB_TOR_EXECUTABLE="$wrapper"
  export DARKWEB_TOR_TRANSPORT_EXECUTABLE="$runtime_root/tor/pluggable_transports/lyrebird"
}

bridge_use_installed_expert_runtime() {
  local current="$TOR_EXPERT_ROOT/current"
  if bridge_configure_expert_runtime "$current"; then
    bridge_warn "using the previously installed Tor Expert Bundle"
    return 0
  fi
  return 1
}

bridge_install_tor_expert_bundle() {
  local architecture version archive_name version_url target current temp_dir archive expected actual
  architecture="$(bridge_expert_architecture)" || {
    bridge_warn "Tor Expert Bundle is unavailable for architecture $(uname -m)"
    return 1
  }
  current="$TOR_EXPERT_ROOT/current"

  if ! version="$(bridge_latest_tor_version)" || [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    bridge_warn "could not determine the current Tor stable version"
    bridge_use_installed_expert_runtime
    return
  fi

  target="$TOR_EXPERT_ROOT/$version"
  if [[ ! -x "$target/tor/tor" || ! -x "$target/tor/pluggable_transports/lyrebird" ]]; then
    archive_name="tor-expert-bundle-linux-${architecture}-${version}.tar.gz"
    version_url="$TOR_DIST_BASE_URL/$version"
    temp_dir="$(mktemp -d)"
    archive="$temp_dir/$archive_name"
    mkdir -p "$temp_dir/unpacked"
    bridge_info "downloading official Tor Expert Bundle $version for $architecture"
    if ! curl -fsSL "$version_url/$archive_name" -o "$archive"; then
      rm -rf "$temp_dir"
      bridge_use_installed_expert_runtime
      return
    fi
    expected="$(curl -fsSL "$version_url/sha256sums-signed-build.txt" |
      awk -v archive="$archive_name" '$2 == archive { print $1; exit }')"
    actual="$(sha256sum "$archive" | awk '{ print $1 }')"
    if [[ -z "$expected" || "$actual" != "$expected" ]]; then
      rm -rf "$temp_dir"
      bridge_warn "Tor Expert Bundle checksum verification failed"
      bridge_use_installed_expert_runtime
      return
    fi
    tar -xzf "$archive" -C "$temp_dir/unpacked"
    if [[ ! -x "$temp_dir/unpacked/tor/tor" || ! -x "$temp_dir/unpacked/tor/pluggable_transports/lyrebird" ]]; then
      rm -rf "$temp_dir"
      bridge_warn "Tor Expert Bundle is missing tor or lyrebird"
      bridge_use_installed_expert_runtime
      return
    fi
    mkdir -p "$TOR_EXPERT_ROOT"
    if [[ -e "$target" ]]; then
      mv "$target" "${target}.invalid.$(date +%s)"
    fi
    mv "$temp_dir/unpacked" "$target"
    rm -rf "$temp_dir"
  fi

  if [[ -e "$current" && ! -L "$current" ]]; then
    bridge_warn "cannot update Tor Expert Bundle link because $current is not a symlink"
    return 1
  fi
  ln -sfn "$target" "$current"
  bridge_configure_expert_runtime "$current"
}

install_tor_bridge_runtime() {
  local prerequisites=()
  command -v curl >/dev/null 2>&1 || prerequisites+=("curl")
  command -v python3 >/dev/null 2>&1 || prerequisites+=("python3")
  command -v tar >/dev/null 2>&1 || prerequisites+=("tar")
  command -v sha256sum >/dev/null 2>&1 || prerequisites+=("coreutils")
  if (( ${#prerequisites[@]} > 0 )); then
    if ! command -v apt-get >/dev/null 2>&1; then
      bridge_warn "missing Tor Expert Bundle prerequisites: ${prerequisites[*]}"
      return 1
    fi
    bridge_install_packages "${prerequisites[@]}"
  fi

  if bridge_install_tor_expert_bundle; then
    bridge_info "Tor bridge runtime:"
    "$DARKWEB_TOR_EXECUTABLE" --version | head -n 1
    "$DARKWEB_TOR_TRANSPORT_EXECUTABLE" -version
    return 0
  fi
  bridge_warn "official Tor Expert Bundle installation failed; falling back to distribution packages"

  if ! command -v apt-get >/dev/null 2>&1; then
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
