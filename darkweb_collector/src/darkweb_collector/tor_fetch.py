from __future__ import annotations

import shutil
import subprocess
import traceback
import time
import os
from urllib.parse import urlparse


class TorFetchError(RuntimeError):
    """Raised when a Tor-backed fetch fails."""


class ProxyFetchError(RuntimeError):
    """Raised when a proxy-backed fetch fails."""


def _stderr_text(stderr: str | bytes | None) -> str:
    if stderr is None:
        return "unknown curl error"
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace").strip()
    return stderr.strip()


def is_onion_hostname(hostname: str | None) -> bool:
    return bool(hostname and hostname.lower().endswith(".onion"))


def is_onion_url(url: str) -> bool:
    return is_onion_hostname(urlparse(url).hostname)


def get_tor_socks_settings() -> tuple[str, int]:
    return os.environ.get("TOR_SOCKS_HOST", "127.0.0.1"), int(os.environ.get("TOR_SOCKS_PORT", "9150"))


def get_http_proxy_settings() -> tuple[str | None, int | None]:
    proxy_host = os.environ.get("PROXY_HOST")
    proxy_port_str = os.environ.get("PROXY_PORT")
    proxy_port = int(proxy_port_str) if proxy_port_str else None
    return proxy_host, proxy_port


def browser_proxy_server_for_url(url: str) -> str | None:
    if is_onion_url(url):
        socks_host, socks_port = get_tor_socks_settings()
        return f"socks5://{socks_host}:{socks_port}"
    proxy_host, proxy_port = get_http_proxy_settings()
    if proxy_host and proxy_port:
        return f"http://{proxy_host}:{proxy_port}"
    return None


def fetch_url(
    url: str,
    mode: str,
    timeout_seconds: int,
    render_wait_seconds: int = 8,
    retries: int = 1,
) -> str:
    if mode == "browser":
        from darkweb_collector.browser_client import fetch_html_with_browser

        return fetch_html_with_browser(
            url=url,
            wait_seconds=render_wait_seconds,
            timeout_seconds=timeout_seconds,
            proxy_server=browser_proxy_server_for_url(url),
        )

    if is_onion_url(url):
        socks_host, socks_port = get_tor_socks_settings()
        return fetch_via_tor_curl(
            url=url,
            socks_host=socks_host,
            socks_port=socks_port,
            timeout=timeout_seconds,
            retries=retries,
        )

    proxy_host, proxy_port = get_http_proxy_settings()
    return fetch_via_http_proxy(
        url=url,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        timeout=timeout_seconds,
        retries=retries,
        backoff_seconds=3.0,
    )


def fetch_page_artifacts(
    url: str,
    mode: str,
    timeout_seconds: int,
    render_wait_seconds: int = 8,
    screenshot_selector: str | None = None,
    screenshot_selectors: tuple[str, ...] = (),
    hide_selectors: tuple[str, ...] = (),
    render_html_for_screenshot: bool = False,
) -> tuple[str, bytes | None]:
    if mode == "browser":
        from darkweb_collector.browser_client import fetch_page_artifacts_with_browser

        html, screenshot_png = fetch_page_artifacts_with_browser(
            url=url,
            wait_seconds=render_wait_seconds,
            timeout_seconds=timeout_seconds,
            proxy_server=browser_proxy_server_for_url(url),
            screenshot_selector=screenshot_selector,
            screenshot_selectors=screenshot_selectors,
            hide_selectors=hide_selectors,
        )
        return html, screenshot_png

    html = fetch_url(
        url=url,
        mode=mode,
        timeout_seconds=timeout_seconds,
        render_wait_seconds=render_wait_seconds,
        retries=1,
    )

    try:
        if render_html_for_screenshot:
            from darkweb_collector.browser_client import screenshot_html_with_browser

            screenshot_png = screenshot_html_with_browser(
                html=html,
                base_url=url,
                wait_seconds=render_wait_seconds,
                timeout_seconds=timeout_seconds,
                proxy_server=browser_proxy_server_for_url(url),
                screenshot_selector=screenshot_selector,
                screenshot_selectors=screenshot_selectors,
                hide_selectors=hide_selectors,
            )
        else:
            from darkweb_collector.browser_client import fetch_page_artifacts_with_browser

            _, screenshot_png = fetch_page_artifacts_with_browser(
                url=url,
                wait_seconds=render_wait_seconds,
                timeout_seconds=timeout_seconds,
                proxy_server=browser_proxy_server_for_url(url),
                screenshot_selector=screenshot_selector,
                screenshot_selectors=screenshot_selectors,
                hide_selectors=hide_selectors,
            )
        return html, screenshot_png
    except Exception as exc:
        print(f"[screenshot] failed for {url}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return html, None


def fetch_via_tor_curl(
    url: str,
    socks_host: str,
    socks_port: int,
    timeout: int = 90,
    retries: int = 0,
    backoff_seconds: float = 2.0,
) -> str:
    curl = shutil.which("curl")
    if not curl:
        raise TorFetchError("curl not found in PATH")

    attempts = retries + 1
    last_error = "unknown curl error"
    for attempt in range(1, attempts + 1):
        command = [
            curl,
            "--socks5-hostname",
            f"{socks_host}:{socks_port}",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(timeout),
            "--user-agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            url,
        ]

        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout

        last_error = _stderr_text(result.stderr)
        if attempt < attempts:
            time.sleep(backoff_seconds * attempt)

    raise TorFetchError(f"curl fetch failed for {url}: {last_error}")

def fetch_with_cloudflare_bypass(
    url: str,
    socks_host: str,
    socks_port: int,
    timeout: int = 90,
    retries: int = 3,
    backoff_seconds: float = 3.0,
) -> str:
    """Fetch URL with Cloudflare protection bypass"""
    import random
    import time
    
    # Add random delay before request
    time.sleep(random.uniform(2, 5))
    
    # Use different user agents
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:123.0) Gecko/20100101 Firefox/123.0"
    ]
    
    # Randomly select a user agent
    user_agent = random.choice(user_agents)
    
    # Generate random accept headers
    accept_languages = [
        "en-US,en;q=0.9",
        "en-GB,en;q=0.9,en-US;q=0.8",
        "en-CA,en;q=0.9,en-US;q=0.8",
        "en-AU,en;q=0.9,en-US;q=0.8"
    ]
    
    accept_language = random.choice(accept_languages)
    
    # Use curl with enhanced anti-crawler headers
    curl = shutil.which("curl")
    if not curl:
        raise TorFetchError("curl not found in PATH")
    
    attempts = retries + 1
    last_error = "unknown curl error"
    
    for attempt in range(1, attempts + 1):
        # Generate random headers using -H option
        headers = [
            f"-H", f"User-Agent: {user_agent}",
            f"-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            f"-H", f"Accept-Language: {accept_language}",
            f"-H", "Accept-Encoding: gzip, deflate, br",
            f"-H", "Connection: keep-alive",
            f"-H", "Upgrade-Insecure-Requests: 1",
            f"-H", "Cache-Control: max-age=0",
            f"-H", "Sec-Fetch-Dest: document",
            f"-H", "Sec-Fetch-Mode: navigate",
            f"-H", "Sec-Fetch-Site: none",
            f"-H", "Sec-Fetch-User: ?1"
        ]
        
        # Build curl command with decompression
        command = [
            curl,
            "--socks5-hostname", f"{socks_host}:{socks_port}",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time", str(timeout),
            "--cookie-jar", "/tmp/cookies.txt",
            "--cookie", "/tmp/cookies.txt",
            "--compressed",  # Automatically decompress gzip/brotli
            "--output", "/tmp/temp.html"  # Save to file to avoid encoding issues
        ] + headers + [url]
        
        # Execute curl command with proper encoding handling
        result = subprocess.run(command, capture_output=True, check=False)
        
        if result.returncode == 0:
            try:
                # Read from the output file
                with open("/tmp/temp.html", "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                
                # Check if we got a Cloudflare page
                if "Checking your browser" in content:
                    # Add more delay and try again
                    time.sleep(random.uniform(5, 10))
                    continue
                return content
            except Exception as e:
                # If reading as UTF-8 fails, try other encodings
                encodings = ['latin-1', 'cp1252']
                for encoding in encodings:
                    try:
                        with open("/tmp/temp.html", "r", encoding=encoding, errors="replace") as f:
                            content = f.read()
                        if "Checking your browser" in content:
                            # Add more delay and try again
                            time.sleep(random.uniform(5, 10))
                            continue
                        return content
                    except:
                        continue
                # If all encodings fail, try binary read
                try:
                    with open("/tmp/temp.html", "rb") as f:
                        content = f.read()
                    return content.decode('utf-8', errors='replace')
                except:
                    return ""
        
        last_error = _stderr_text(result.stderr)
        if attempt < attempts:
            # Add exponential backoff
            time.sleep(backoff_seconds * attempt)
    
    raise TorFetchError(f"Cloudflare bypass failed for {url}: {last_error}")


def fetch_via_http_proxy(
    url: str,
    proxy_host: str = None,
    proxy_port: int = None,
    timeout: int = 90,
    retries: int = 3,
    backoff_seconds: float = 3.0,
) -> str:
    """
    Fetch URL using HTTP/HTTPS proxy (e.g., Clash, Shadowsocks, etc.)
    If no proxy is configured, fetches directly.
    
    Args:
        url: The URL to fetch
        proxy_host: Proxy host (default: from env PROXY_HOST or None)
        proxy_port: Proxy port (default: from env PROXY_PORT or None)
        timeout: Request timeout in seconds
        retries: Number of retries on failure
        backoff_seconds: Base backoff time between retries
    
    Returns:
        The HTML content of the page
    """
    import random
    
    # Get proxy settings from environment (no defaults - must be explicitly set)
    proxy_host = proxy_host or os.environ.get("PROXY_HOST")
    proxy_port_str = os.environ.get("PROXY_PORT")
    proxy_port = proxy_port or (int(proxy_port_str) if proxy_port_str else None)
    
    # Use different user agents
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:123.0) Gecko/20100101 Firefox/123.0"
    ]
    
    # Randomly select a user agent
    user_agent = random.choice(user_agents)
    
    # Generate random accept headers
    accept_languages = [
        "en-US,en;q=0.9",
        "en-GB,en;q=0.9,en-US;q=0.8",
        "en-CA,en;q=0.9,en-US;q=0.8",
        "en-AU,en;q=0.9,en-US;q=0.8"
    ]
    
    accept_language = random.choice(accept_languages)
    
    # Use curl with HTTP proxy
    curl = shutil.which("curl")
    if not curl:
        raise ProxyFetchError("curl not found in PATH")
    
    attempts = retries + 1
    last_error = "unknown curl error"
    
    # Create temp directory for cookies and output
    temp_dir = os.environ.get("TEMP", "/tmp")
    cookie_file = os.path.join(temp_dir, "cookies.txt")
    output_file = os.path.join(temp_dir, "temp.html")
    
    # Ensure temp directory exists
    os.makedirs(temp_dir, exist_ok=True)
    
    for attempt in range(1, attempts + 1):
        # Generate headers
        # Note: Not sending Accept-Encoding to avoid compressed responses
        headers = [
            f"-H", f"User-Agent: {user_agent}",
            f"-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            f"-H", f"Accept-Language: {accept_language}",
            f"-H", "Connection: keep-alive",
            f"-H", "Upgrade-Insecure-Requests: 1",
            f"-H", "Cache-Control: max-age=0",
            f"-H", "Sec-Fetch-Dest: document",
            f"-H", "Sec-Fetch-Mode: navigate",
            f"-H", "Sec-Fetch-Site: none",
            f"-H", "Sec-Fetch-User: ?1",
            f"-H", "DNT: 1"
        ]
        
        # Build curl command
        command = [
            curl,
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time", str(timeout),
            "--cookie-jar", cookie_file,
            "--cookie", cookie_file,
            "--output", output_file
        ]
        
        # Add proxy if configured
        if proxy_host and proxy_port:
            command.extend(["--proxy", f"http://{proxy_host}:{proxy_port}"])
        
        command.extend(headers + [url])
        
        # Execute curl command
        result = subprocess.run(command, capture_output=True, check=False)
        
        if result.returncode == 0:
            try:
                # Try UTF-8 first
                with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                
                # Check if we got a Cloudflare/interstitial page
                if "Checking your browser" in content or "cf-browser-verification" in content:
                    time.sleep(random.uniform(5, 10))
                    continue
                    
                return content
            except Exception:
                # Try other encodings
                encodings = ['latin-1', 'cp1252']
                for encoding in encodings:
                    try:
                        with open(output_file, "r", encoding=encoding, errors="replace") as f:
                            content = f.read()
                        if "Checking your browser" in content or "cf-browser-verification" in content:
                            time.sleep(random.uniform(5, 10))
                            continue
                        return content
                    except:
                        continue
                
                # Binary read as fallback
                try:
                    with open(output_file, "rb") as f:
                        content = f.read()
                    return content.decode('utf-8', errors='replace')
                except:
                    return ""
        
        last_error = _stderr_text(result.stderr)
        if attempt < attempts:
            time.sleep(backoff_seconds * attempt)
    
    raise ProxyFetchError(f"Proxy fetch failed for {url}: {last_error}")


def fetch_with_proxy_bypass(
    url: str,
    proxy_host: str = None,
    proxy_port: int = None,
    timeout: int = 90,
    retries: int = 3,
) -> str:
    """
    Fetch URL with proxy and anti-detection measures
    
    This is a convenience wrapper around fetch_via_http_proxy
    """
    return fetch_via_http_proxy(
        url=url,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        timeout=timeout,
        retries=retries,
        backoff_seconds=3.0
    )
