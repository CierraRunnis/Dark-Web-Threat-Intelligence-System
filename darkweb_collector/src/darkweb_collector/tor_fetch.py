from __future__ import annotations

import shutil
import socket
import struct
import subprocess
import traceback
import time
import os
from urllib.parse import urlparse


_PROXY_ENV_VARS = (
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "all_proxy",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)


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


def _env_without_proxy_settings() -> dict[str, str]:
    env = os.environ.copy()
    for key in _PROXY_ENV_VARS:
        env.pop(key, None)
    return env


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


def browser_proxy_server_for_url(url: str, mode: str | None = None) -> str | None:
    # tor_http means "this site must exit via Tor regardless of TLD" — used
    # for clearnet sites (e.g. darkforums.as) where the configured HTTP proxy
    # node is blocked by the target's WAF but Tor exit nodes are not.
    if mode == "tor_http" or is_onion_url(url):
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
    cookie_header: str | None = None,
) -> str:
    if mode == "browser":
        from darkweb_collector.browser_client import fetch_html_with_browser

        return fetch_html_with_browser(
            url=url,
            wait_seconds=render_wait_seconds,
            timeout_seconds=timeout_seconds,
            proxy_server=browser_proxy_server_for_url(url, mode),
        )

    if mode == "tor_http" or is_onion_url(url):
        socks_host, socks_port = get_tor_socks_settings()
        return fetch_via_tor_curl(
            url=url,
            socks_host=socks_host,
            socks_port=socks_port,
            timeout=timeout_seconds,
            retries=retries,
            cookie_header=cookie_header,
        )

    proxy_host, proxy_port = get_http_proxy_settings()
    return fetch_via_http_proxy(
        url=url,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        timeout=timeout_seconds,
        retries=retries,
        backoff_seconds=3.0,
        cookie_header=cookie_header,
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
    cookie_header: str | None = None,
) -> tuple[str, bytes | None]:
    if mode == "browser":
        from darkweb_collector.browser_client import fetch_page_artifacts_with_browser

        html, screenshot_png = fetch_page_artifacts_with_browser(
            url=url,
            wait_seconds=render_wait_seconds,
            timeout_seconds=timeout_seconds,
            proxy_server=browser_proxy_server_for_url(url, mode),
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
        cookie_header=cookie_header,
    )

    try:
        if render_html_for_screenshot:
            from darkweb_collector.browser_client import screenshot_html_with_browser

            screenshot_png = screenshot_html_with_browser(
                html=html,
                base_url=url,
                wait_seconds=render_wait_seconds,
                timeout_seconds=timeout_seconds,
                proxy_server=browser_proxy_server_for_url(url, mode),
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
                proxy_server=browser_proxy_server_for_url(url, mode),
                screenshot_selector=screenshot_selector,
                screenshot_selectors=screenshot_selectors,
                hide_selectors=hide_selectors,
            )
        return html, screenshot_png
    except Exception as exc:
        print(f"[screenshot] failed for {url}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return html, None


def _fetch_onion_via_socks5(
    url: str,
    socks_host: str,
    socks_port: int,
    timeout: int = 90,
    retries: int = 0,
    backoff_seconds: float = 2.0,
    cookie_header: str | None = None,
) -> str:
    """Fetch a .onion URL via raw SOCKS5 socket + HTTP/1.1.

    This bypasses libcurl entirely, avoiding the RFC 7686 .onion block
    present in curl/libcurl 8.5.0 on Ubuntu 24.04.  The SOCKS5 handshake
    uses ATYP=DOMAINNAME (0x03) so the proxy resolves the .onion hostname.
    """
    import socks  # PySocks

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    attempts = retries + 1
    last_error: str = "unknown error"

    for attempt in range(1, attempts + 1):
        sock = None
        try:
            sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
            sock.set_proxy(socks.SOCKS5, socks_host, socks_port, rdns=True)
            sock.settimeout(timeout)
            sock.connect((host, port))

            # Build HTTP/1.1 request
            headers_lines = [
                f"GET {path} HTTP/1.1",
                f"Host: {host}",
                f"User-Agent: {user_agent}",
                "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language: en-US,en;q=0.9",
                "Connection: close",
            ]
            if cookie_header:
                headers_lines.append(f"Cookie: {cookie_header}")
            request_bytes = ("\r\n".join(headers_lines) + "\r\n\r\n").encode("utf-8")
            sock.sendall(request_bytes)

            # Read full response
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)

            # Split headers from body
            header_end = raw.find(b"\r\n\r\n")
            if header_end == -1:
                raise TorFetchError(f"Malformed HTTP response from {url}")
            header_block = raw[:header_end].decode("utf-8", errors="replace")
            body = raw[header_end + 4:]

            # Check status line
            status_line = header_block.split("\r\n")[0]
            # e.g. "HTTP/1.1 200 OK"
            parts = status_line.split(" ", 2)
            status_code = int(parts[1]) if len(parts) >= 2 else 0

            # Handle redirects (301, 302, 303, 307, 308)
            if status_code in (301, 302, 303, 307, 308):
                for line in header_block.split("\r\n"):
                    if line.lower().startswith("location:"):
                        redirect_url = line.split(":", 1)[1].strip()
                        # Handle relative redirects
                        if redirect_url.startswith("/"):
                            redirect_url = f"http://{host}:{port}{redirect_url}"
                        sock.close()
                        return _fetch_onion_via_socks5(
                            url=redirect_url,
                            socks_host=socks_host,
                            socks_port=socks_port,
                            timeout=timeout,
                            retries=0,
                            cookie_header=cookie_header,
                        )

            if status_code >= 400:
                raise TorFetchError(
                    f"HTTP {status_code} from {url}: {status_line}"
                )

            # Handle chunked transfer encoding
            is_chunked = "transfer-encoding: chunked" in header_block.lower()
            if is_chunked:
                body = _decode_chunked(body)

            return body.decode("utf-8", errors="replace")

        except TorFetchError:
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    raise TorFetchError(f"SOCKS5 fetch failed for {url}: {last_error}")


def _decode_chunked(data: bytes) -> bytes:
    """Decode HTTP chunked transfer encoding."""
    result = bytearray()
    idx = 0
    while idx < len(data):
        # Find chunk size line
        line_end = data.find(b"\r\n", idx)
        if line_end == -1:
            break
        size_str = data[idx:line_end].decode("ascii", errors="replace").strip()
        if not size_str:
            idx = line_end + 2
            continue
        # Chunk size may have extensions after semicolon
        size_str = size_str.split(";")[0].strip()
        try:
            chunk_size = int(size_str, 16)
        except ValueError:
            break
        if chunk_size == 0:
            break
        chunk_start = line_end + 2
        chunk_end = chunk_start + chunk_size
        result.extend(data[chunk_start:chunk_end])
        idx = chunk_end + 2  # skip trailing \r\n
    return bytes(result)


def fetch_via_tor_curl(
    url: str,
    socks_host: str,
    socks_port: int,
    timeout: int = 90,
    retries: int = 0,
    backoff_seconds: float = 2.0,
    cookie_header: str | None = None,
) -> str:
    curl = shutil.which("curl")
    if not curl:
        # No curl available at all — go straight to Python SOCKS5 fallback
        return _fetch_onion_via_socks5(
            url=url,
            socks_host=socks_host,
            socks_port=socks_port,
            timeout=timeout,
            retries=retries,
            backoff_seconds=backoff_seconds,
            cookie_header=cookie_header,
        )

    attempts = retries + 1
    last_error = "unknown curl error"
    curl_env = _env_without_proxy_settings()
    for attempt in range(1, attempts + 1):
        command = [
            curl,
            # Use the canonical socks5h:// URL scheme (NOT --socks5-hostname),
            # because curl 8.5.0 on Ubuntu has the RFC 7686 check fire before
            # the short-flag is mapped to SOCKS5_HOSTNAME, so .onion errors
            # with "Not resolving .onion address (RFC 7686)" even though the
            # intent is exactly remote-DNS-through-SOCKS5.
            "--proxy",
            f"socks5h://{socks_host}:{socks_port}",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(timeout),
            "--user-agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]
        if cookie_header:
            command.extend(["--cookie", cookie_header])
        command.append(url)

        # Capture as bytes and decode as UTF-8 explicitly. text=True relies on
        # the platform default encoding (GBK on zh_CN Windows), which corrupts
        # non-ASCII forum content; the bodies we fetch are virtually always UTF-8.
        result = subprocess.run(command, capture_output=True, check=False, env=curl_env)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")

        last_error = _stderr_text(result.stderr)

        # Detect the RFC 7686 .onion block from curl 8.5.0+ on Ubuntu 24.04.
        # When this happens, curl will never succeed for .onion URLs regardless
        # of retries, so fall back to the pure-Python SOCKS5 implementation.
        if "not resolving .onion" in last_error.lower():
            print(
                f"[tor_fetch] curl blocked .onion (RFC 7686); "
                f"falling back to Python SOCKS5 for {url}"
            )
            return _fetch_onion_via_socks5(
                url=url,
                socks_host=socks_host,
                socks_port=socks_port,
                timeout=timeout,
                retries=retries,
                backoff_seconds=backoff_seconds,
                cookie_header=cookie_header,
            )

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
        
        curl_env = _env_without_proxy_settings()

        # Build curl command with decompression
        command = [
            curl,
            # Use an explicit SOCKS5h proxy so curl resolves hostnames through Tor.
            "--proxy", f"socks5h://{socks_host}:{socks_port}",
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
        result = subprocess.run(command, capture_output=True, check=False, env=curl_env)
        
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
    cookie_header: str | None = None,
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

        if cookie_header:
            command.extend(["--cookie", cookie_header])

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
