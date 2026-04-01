#!/bin/bash
# Run onion crawler with Playwright in WSL with Tor

cd /mnt/d/bishe/darkweb_collector

# Activate virtual environment
source venv/bin/activate

# Set Tor proxy (WSL connects to Windows host's Tor Browser on port 9150)
export TOR_SOCKS_HOST="127.0.0.1"
export TOR_SOCKS_PORT="9150"

echo "Connecting to Tor: $TOR_SOCKS_HOST:$TOR_SOCKS_PORT"

# Run the crawler with Playwright
python scripts/fetch_onion_playwright.py "http://hptqq2o2qjva7lcaaq67w36jihzivkaitkexorauw7b2yul2z6zozpqd.onion/"
