# Tor Bridge Control

This directory contains the Tor bridge control feature used by the collector UI.
It is intentionally self-contained so it can be uploaded or reused without
copying the whole project.

The module:

- stores bridge settings in `tor_bridge_settings.json`
- generates a dedicated `torrc`
- starts and stops a local `tor.exe`
- exposes the effective SOCKS endpoint to collector fetch code

It does not bundle Tor binaries. Point `tor_executable` to a Tor Expert Bundle
or Tor Browser `tor.exe`, and point `transport_executable` to the matching
pluggable transport binary, such as `snowflake-client.exe` or `lyrebird.exe`.

