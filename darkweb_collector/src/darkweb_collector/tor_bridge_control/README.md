# Tor Bridge Control

This directory contains the Tor bridge control feature used by the collector UI.
It is intentionally self-contained so it can be uploaded or reused without
copying the whole project.

The module:

- stores bridge settings in `tor_bridge_settings.json`
- generates a dedicated `torrc`
- starts and stops a local Tor process
- exposes the effective SOCKS endpoint to collector fetch code

Linux/WSL startup installs the system packages needed by the built-in bridge
modes: `tor`, `snowflake-client`, and `obfs4proxy`. Codespaces run
`.devcontainer/install-tor-bridge-runtime.sh` after creation for the same
runtime.

Windows startup detects Tor Browser or Tor Expert Bundle paths and passes them
to the API through `DARKWEB_TOR_EXECUTABLE` and
`DARKWEB_TOR_TRANSPORT_EXECUTABLE`. Windows does not silently install Tor
Browser. If detection fails, point `tor_executable` to a Tor Expert Bundle or
Tor Browser `tor.exe`, and point `transport_executable` to the matching
pluggable transport binary, such as `snowflake-client.exe` or `lyrebird.exe`.

