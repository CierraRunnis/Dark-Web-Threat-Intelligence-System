#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash install/install_wsl_tor_bundle.sh" >&2
  exit 1
fi

pkg_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install -d -m 0755 /etc/tor
install -d -m 0755 /usr/local/bin
install -d -m 0755 /etc/systemd/system/tor@default.service.d

install -m 0644 "${pkg_root}/etc/tor/"* /etc/tor/
install -m 0755 "${pkg_root}/usr/local/bin/"* /usr/local/bin/
install -m 0644 "${pkg_root}/systemd/tor@default.service.d/proxy.conf" /etc/systemd/system/tor@default.service.d/proxy.conf

target_user="${SUDO_USER:-${USER:-}}"
if [[ -n "${target_user}" && "${target_user}" != "root" ]] && id -u "${target_user}" >/dev/null 2>&1; then
  target_home="$(getent passwd "${target_user}" | cut -d: -f6)"
  if [[ -n "${target_home}" && -d "${target_home}" && -f "${pkg_root}/home/user/.wsl-proxy-env.sh" ]]; then
    install -m 0644 "${pkg_root}/home/user/.wsl-proxy-env.sh" "${target_home}/.wsl-proxy-env.sh"
    chown "${target_user}:${target_user}" "${target_home}/.wsl-proxy-env.sh"
  fi
fi

systemctl daemon-reload

echo "Installed Tor migration bundle."
echo "Next steps:"
echo "  sudo tor-bridge-switch webtunnel"
echo "  curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip"
