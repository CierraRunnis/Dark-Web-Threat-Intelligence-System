# Tor Migration Package

This package contains the working Tor bridge setup prepared in WSL Ubuntu.

Contents:

- `etc/tor/`: Tor bridge templates, current bridge pools, refresh hooks
- `usr/local/bin/`: switching scripts, bridge fetcher, `lyrebird`
- `systemd/tor@default.service.d/proxy.conf`: optional proxy environment drop-in
- `torbrowser-socks-env.sh`: WSL helper for reusing Windows Tor Browser SOCKS
- `torbrowser-socks-check.sh`: quick connectivity test through Tor Browser SOCKS
- `windows/.wslconfig.sample`: recommended Windows WSL networking config
- `install/install_wsl_tor_bundle.sh`: installer for Ubuntu/WSL targets

Recommended migration flow:

1. Copy this package into the target machine.
2. On Windows, merge `windows/.wslconfig.sample` into `%UserProfile%\\.wslconfig` if needed.
3. In the target WSL distro, run:

```bash
sudo bash install/install_wsl_tor_bundle.sh
sudo tor-bridge-switch webtunnel
```

Useful commands after install:

```bash
sudo tor-bridge-switch status
sudo tor-bridge-switch webtunnel
sudo tor-bridge-switch auto
sudo tor-bridge-refresh
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
```

Recommended workflow for research and crawling:

```bash
source ./torbrowser-socks-env.sh
curl https://check.torproject.org/api/ip
```

Or test directly against Tor Browser SOCKS:

```bash
./torbrowser-socks-check.sh
```

Notes:

- Reusing Windows Tor Browser SOCKS is currently more stable than making WSL `tor` negotiate bridges on its own.
- `webtunnel` is the best packaged fallback mode for system `tor` in this environment.
- `snowflake` and `obfs4` remain packaged as fallback modes.
- `meek` is supported by the switching framework, but the package does not include valid meek bridge lines.
- BridgeDB HTML cleaning is already built into `bridgedb-fetch`.
