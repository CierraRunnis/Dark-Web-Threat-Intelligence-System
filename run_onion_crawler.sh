#!/bin/bash
# Run onion crawler in WSL

cd /mnt/d/bishe/darkweb_collector

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install required packages
pip install requests pysocks

# Run the crawler
python scripts/fetch_onion_requests.py "http://hptqq2o2qjva7lcaaq67w36jihzivkaitkexorauw7b2yul2z6zozpqd.onion/"
