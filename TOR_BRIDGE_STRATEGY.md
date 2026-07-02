## Tor Bridge Strategy

This machine keeps a multi-mode system-level Tor bridge framework:

- `snowflake`: default profile for broad compatibility
- `obfs4`: backup profile for private bridge testing
- `webtunnel`: prepared and can auto-fetch bridge lines
- `vanilla`: prepared and can auto-fetch bridge lines
- `meek`: prepared, but requires `lyrebird` and valid bridge lines

Current host state:

- `snowflake-client` is installed
- `obfs4proxy` is installed
- `lyrebird` is installed at `/usr/local/bin/lyrebird`
- `tor@default.service` can read proxy variables from `/etc/tor/proxy.env`
- WSL can directly use Windows Tor Browser SOCKS at `127.0.0.1:9150`
- `snowflake` can be selected automatically
- `obfs4` can auto-refresh bridge lines from `bridges.torproject.org`
- `webtunnel` can auto-refresh bridge lines from `bridges.torproject.org`
- `vanilla` can auto-refresh bridge lines from `bridges.torproject.org`
- `meek` now has a runnable transport binary, but still needs valid bridge lines in `bridges.meek`

Available commands in WSL:

```bash
sudo tor-bridge-switch snowflake
sudo tor-bridge-switch obfs4
sudo tor-bridge-switch webtunnel
sudo tor-bridge-switch vanilla
sudo tor-bridge-switch meek
sudo tor-bridge-switch auto
sudo tor-bridge-switch status
sudo tor-bridge-refresh
sudo wsl-sync-proxy-env
```

Recommended WSL research path:

- Start Tor Browser on Windows
- In WSL, prefer the Tor Browser SOCKS endpoint over system `tor` for crawling and collection

Quick test:

```bash
curl --socks5-hostname 127.0.0.1:9150 https://check.torproject.org/api/ip
```

Reusable shell helper:

```bash
source /mnt/d/project/torbrowser-socks-env.sh
curl https://check.torproject.org/api/ip
```

Bridge source files on this host:

- `/etc/tor/bridges.obfs4`
- `/etc/tor/bridges.webtunnel`
- `/etc/tor/bridges.vanilla`
- `/etc/tor/bridges.meek`
- `/etc/tor/bridge-order.conf`

Optional automatic bridge fetch hooks:

- `/etc/tor/bridge-fetch.obfs4`
- `/etc/tor/bridge-fetch.webtunnel`
- `/etc/tor/bridge-fetch.vanilla`
- `/etc/tor/bridge-fetch.meek`

Each hook is an executable script that prints valid `Bridge ...` lines to stdout.
Sample hook files are stored as `.sample` next to them.
The default `obfs4`, `webtunnel`, and `vanilla` hooks now call `bridges.torproject.org/bridges?transport=...`.

WSL host proxy sync:

- `/usr/local/bin/wsl-sync-proxy-env` probes the Windows host gateway and writes `/etc/tor/proxy.env`
- `tor@default.service` reads `/etc/tor/proxy.env` through `/etc/systemd/system/tor@default.service.d/proxy.conf`

Cross-device fallback order:

1. Snowflake
2. Private obfs4 bridges
3. meek-azure in Tor Browser, Onion Browser, or Orbot
4. WebTunnel where the client supports it

Why `meek-azure` is not fully wired into `/etc/tor/torrc` here:

- This Ubuntu host has `snowflake-client` and `obfs4proxy`.
- `lyrebird` was built locally because the official Tor binary distribution host was unreachable from this environment.
- Tor's official little-t-tor support page documents syntax for `meek_lite,obfs4,snowflake,webtunnel`, but it does not publish stable built-in `webtunnel` or `meek` bridge lines for system `tor`.
- On other devices, prefer the client application's built-in bridge support instead of maintaining a custom `torrc`.

Operational rule:

- Treat public bridges as disposable.
- Keep fresh bridge pools for `obfs4` and `webtunnel`.
- Use `tor-bridge-refresh` plus fetch hooks to update bridge pools without editing `torrc`.
- Use built-in bridges on desktop/mobile clients whenever possible.
