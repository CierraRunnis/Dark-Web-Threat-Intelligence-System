#!/usr/bin/env bash
#
# tor_healthcheck.sh
#
# Pick a working Tor SOCKS5 endpoint for the bishe darkweb_collector stack.
#
# Probe order matches TOR_CONNECTION_PLAN.md:
#   L1: 127.0.0.1:9150              (Windows Tor Browser via mirrored networking)
#   L2: 127.0.0.1:9050              (WSL system tor@default.service)
#   L3: <default_gateway>:9150      (Windows Tor Browser via gateway IP)
#
# A probe is considered successful only when a real Tor circuit can complete
# a request to https://check.torproject.org/api/ip, not merely when the TCP
# port is reachable.
#
# If L2 is unreachable and /usr/local/bin/tor-bridge-switch is available with
# passwordless sudo, one auto-switch attempt is made before re-probing L2.
#
# Usage:
#   bash tor_healthcheck.sh                # human readable report
#   bash tor_healthcheck.sh --export       # shell exports for eval "$(...)"
#   bash tor_healthcheck.sh --quiet        # minimal output, exit code only
#
# Environment:
#   TOR_HEALTHCHECK_TIMEOUT   per-probe curl timeout in seconds (default 15)
#   TOR_HEALTHCHECK_TEST_URL  URL used to confirm the circuit is usable
#                             (default https://check.torproject.org/api/ip)
#   TOR_HEALTHCHECK_STATE     path to write the selected endpoint env-file
#                             (default $XDG_RUNTIME_DIR/bishe-tor-endpoint.env
#                             or /tmp/bishe-tor-endpoint.env)
#
# Exit codes:
#   0  one of L1 / L2 / L3 works, selected endpoint is reported
#   1  no endpoint works
#   2  bad CLI usage
#
set -u

mode="report"
for arg in "$@"; do
  case "$arg" in
    --export) mode="export" ;;
    --quiet)  mode="quiet" ;;
    -h|--help)
      sed -n '2,32p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

timeout_seconds="${TOR_HEALTHCHECK_TIMEOUT:-15}"
test_url="${TOR_HEALTHCHECK_TEST_URL:-https://check.torproject.org/api/ip}"
state_file="${TOR_HEALTHCHECK_STATE:-}"
if [[ -z "$state_file" ]]; then
  if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "${XDG_RUNTIME_DIR}" ]]; then
    state_file="${XDG_RUNTIME_DIR}/bishe-tor-endpoint.env"
  else
    state_file="/tmp/bishe-tor-endpoint.env"
  fi
fi

log() {
  if [[ "$mode" != "quiet" && "$mode" != "export" ]]; then
    printf '[tor-healthcheck] %s\n' "$*" >&2
  fi
}

detect_gateway() {
  local gw
  gw="$(ip route 2>/dev/null | awk '/^default/ {print $3; exit}')"
  if [[ -z "$gw" ]]; then
    # Fallbacks for WSL environments where `ip` is unavailable or routing is mirrored.
    for candidate in 172.17.0.1 172.18.0.1 172.19.0.1 172.20.0.1 172.21.0.1 172.22.0.1 172.23.0.1 172.24.0.1 172.25.0.1 172.26.0.1 172.27.0.1 172.28.0.1 172.29.0.1 172.30.0.1 172.31.0.1; do
      if timeout 1 bash -c "</dev/tcp/${candidate}/9150" >/dev/null 2>&1; then
        gw="$candidate"
        break
      fi
    done
  fi
  printf '%s' "$gw"
}

tcp_open() {
  local host="$1"
  local port="$2"
  timeout 2 bash -c "</dev/tcp/${host}/${port}" >/dev/null 2>&1
}

probe_socks() {
  local host="$1"
  local port="$2"
  if ! tcp_open "$host" "$port"; then
    return 1
  fi
  curl --socks5-hostname "${host}:${port}" \
    --fail --silent --show-error --location \
    --max-time "${timeout_seconds}" \
    -o /dev/null \
    "${test_url}"
}

try_auto_switch() {
  local switcher="/usr/local/bin/tor-bridge-switch"
  if [[ ! -x "$switcher" ]]; then
    return 1
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    log "L2 not responding, running tor-bridge-switch auto"
    "$switcher" auto >/dev/null 2>&1
    return $?
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    log "L2 not responding, running sudo tor-bridge-switch auto"
    sudo -n "$switcher" auto >/dev/null 2>&1
    return $?
  fi
  log "skipping tor-bridge-switch auto (no passwordless sudo)"
  return 1
}

write_state() {
  local host="$1"
  local port="$2"
  local layer="$3"
  local dir
  dir="$(dirname "$state_file")"
  mkdir -p "$dir" 2>/dev/null || true
  {
    printf 'TOR_SOCKS_HOST=%s\n' "$host"
    printf 'TOR_SOCKS_PORT=%s\n' "$port"
    printf 'TOR_SOCKS_LAYER=%s\n' "$layer"
    printf 'TOR_SOCKS_SELECTED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$state_file" 2>/dev/null || true
}

emit_result() {
  local host="$1"
  local port="$2"
  local layer="$3"
  write_state "$host" "$port" "$layer"
  case "$mode" in
    export)
      printf 'export TOR_SOCKS_HOST=%s\n' "$host"
      printf 'export TOR_SOCKS_PORT=%s\n' "$port"
      printf 'export TOR_SOCKS_LAYER=%s\n' "$layer"
      ;;
    quiet)
      :
      ;;
    *)
      printf 'selected %s  TOR_SOCKS_HOST=%s TOR_SOCKS_PORT=%s\n' "$layer" "$host" "$port"
      printf 'state written to %s\n' "$state_file"
      ;;
  esac
}

emit_failure() {
  case "$mode" in
    export)
      printf '# tor_healthcheck: no working endpoint\n'
      printf 'unset TOR_SOCKS_HOST TOR_SOCKS_PORT TOR_SOCKS_LAYER\n'
      ;;
    quiet)
      :
      ;;
    *)
      printf 'no working Tor SOCKS endpoint (L1/L2/L3 all failed)\n' >&2
      ;;
  esac
}

# L1: Windows Tor Browser via localhost (mirrored networking)
log "probing L1 at 127.0.0.1:9150"
if probe_socks 127.0.0.1 9150; then
  emit_result 127.0.0.1 9150 L1
  exit 0
fi
log "L1 failed"

# L2: WSL system tor
log "probing L2 at 127.0.0.1:9050"
if probe_socks 127.0.0.1 9050; then
  emit_result 127.0.0.1 9050 L2
  exit 0
fi
log "L2 failed"

# L2 recovery: try auto switch once, then re-probe.
if try_auto_switch; then
  log "re-probing L2 after tor-bridge-switch auto"
  if probe_socks 127.0.0.1 9050; then
    emit_result 127.0.0.1 9050 L2
    exit 0
  fi
  log "L2 still failing after auto switch"
fi

# L3: Tor Browser via WSL default gateway IP
gateway="$(detect_gateway)"
if [[ -n "$gateway" ]]; then
  log "probing L3 at ${gateway}:9150"
  if probe_socks "$gateway" 9150; then
    emit_result "$gateway" 9150 L3
    exit 0
  fi
  log "L3 failed"
else
  log "no default gateway detected, skipping L3"
fi

emit_failure
exit 1
