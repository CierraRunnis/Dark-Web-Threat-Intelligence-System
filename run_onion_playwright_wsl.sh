#!/bin/bash
# Run onion crawler with Playwright in WSL with Tor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/darkweb_collector" && pwd)"

cd "$PROJECT_ROOT"

# Activate virtual environment
source venv/bin/activate

# Set Tor proxy (WSL connects to Windows host's Tor Browser on port 9150)
export TOR_SOCKS_HOST="127.0.0.1"
export TOR_SOCKS_PORT="9150"

echo "Connecting to Tor: $TOR_SOCKS_HOST:$TOR_SOCKS_PORT"

# Run the crawler with Playwright
python scripts/fetch_onion_playwright.py "http://hptqq2o2qjva7lcaaq67w36jihzivkaitkexorauw7b2yul2z6zozpqd.onion/"
