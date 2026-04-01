#!/usr/bin/env python3
"""
Onion Site Crawler using Playwright - For Windows with Tor Browser

This script uses Playwright to crawl .onion websites through Tor Browser proxy.
Run this directly on Windows (not in WSL).

Requirements:
    pip install playwright
    playwright install firefox
    
Usage:
    python fetch_onion_playwright_windows.py <onion_url>
    
Environment variables:
    TOR_SOCKS_HOST: Tor SOCKS proxy host (default: 127.0.0.1)
    TOR_SOCKS_PORT: Tor SOCKS proxy port (default: 9150)
"""
from __future__ import annotations

import json
import os
import random
import time
import sys
from pathlib import Path
from urllib.parse import urlparse


def fetch_onion_with_playwright(url: str, socks_host: str = "127.0.0.1", socks_port: int = 9150, wait_time: int = 20) -> str:
    """
    Fetch an .onion URL using Playwright through Tor SOCKS proxy
    
    Args:
        url: The .onion URL to fetch
        socks_host: Tor SOCKS proxy host
        socks_port: Tor SOCKS proxy port
        wait_time: Time to wait for page to load (seconds)
        
    Returns:
        The rendered HTML content of the page
    """
    from playwright.sync_api import sync_playwright
    
    print(f"[{time.strftime('%H:%M:%S')}] 🔒 Setting up Playwright with Tor proxy: {socks_host}:{socks_port}")
    
    with sync_playwright() as p:
        # Launch browser with proxy
        browser = p.firefox.launch(
            headless=True,
            proxy={
                "server": f"socks5://{socks_host}:{socks_port}"
            }
        )
        
        # Create new page
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
        )
        page = context.new_page()
        
        try:
            print(f"[{time.strftime('%H:%M:%S')}] 🌐 Navigating to: {url}")
            # Use domcontentloaded instead of networkidle for faster loading
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            
            # Wait for page to load
            print(f"[{time.strftime('%H:%M:%S')}] ⏱️  Waiting {wait_time}s for page to render...")
            time.sleep(wait_time)
            
            # Get page content
            html = page.content()
            print(f"[{time.strftime('%H:%M:%S')}] ✅ Successfully fetched {len(html)} bytes")
            
            # Close browser
            browser.close()
            
            return html
            
        except Exception as e:
            browser.close()
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Playwright error: {e}")
            raise


def save_output(url: str, html: str, output_dir: Path) -> None:
    """Save the fetched HTML to file"""
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename from URL
    parsed = urlparse(url)
    domain = parsed.netloc.replace('.', '_')
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    
    # Save HTML
    html_path = output_dir / f"{domain}_playwright_{timestamp}.html"
    with open(html_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(html)
    print(f"[{time.strftime('%H:%M:%S')}] 💾 Saved HTML to: {html_path}")
    
    # Save metadata
    meta_path = output_dir / f"{domain}_playwright_{timestamp}.json"
    metadata = {
        "url": url,
        "domain": parsed.netloc,
        "fetched_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "content_length": len(html),
        "method": "playwright_windows",
        "html_file": str(html_path.name)
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"[{time.strftime('%H:%M:%S')}] 💾 Saved metadata to: {meta_path}")


def main() -> None:
    """Main function"""
    # Get URL from command line or use default
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "http://hptqq2o2qjva7lcaaq67w36jihzivkaitkexorauw7b2yul2z6zozpqd.onion/"
    
    # Validate URL
    if not url.endswith('.onion/'):
        print(f"⚠️  Warning: URL doesn't look like a .onion address: {url}")
    
    # Get Tor proxy settings (default to 9150 for Tor Browser)
    socks_host = os.environ.get("TOR_SOCKS_HOST", "127.0.0.1")
    socks_port = int(os.environ.get("TOR_SOCKS_PORT", "9150"))
    
    print("\n" + "="*60)
    print(f"[{time.strftime('%H:%M:%S')}] 🧅 ONION SITE CRAWLER (Playwright - Windows)")
    print(f"[{time.strftime('%H:%M:%S')}] 📍 Target: {url}")
    print(f"[{time.strftime('%H:%M:%S')}] 🔒 Tor Proxy: {socks_host}:{socks_port}")
    print("="*60 + "\n")
    
    try:
        # Fetch the onion site with Playwright
        html = fetch_onion_with_playwright(url, socks_host, socks_port, wait_time=25)
        
        # Save output
        output_dir = Path(__file__).parent.parent / "output" / "onion_sites"
        save_output(url, html, output_dir)
        
        # Print preview
        print(f"\n[{time.strftime('%H:%M:%S')}] 📄 Content Preview (first 2000 chars):")
        print("-" * 60)
        print(html[:2000])
        print("-" * 60)
        
        print(f"\n[{time.strftime('%H:%M:%S')}] ✅ Crawling completed successfully!")
        
    except Exception as e:
        print(f"\n[{time.strftime('%H:%M:%S')}] ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
