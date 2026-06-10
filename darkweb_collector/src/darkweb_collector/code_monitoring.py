from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
from html import unescape
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from darkweb_collector.db import (
    add_code_hit_review,
    get_code_hit,
    get_code_watchlist,
    get_db_connection,
    insert_code_hit_snapshot,
    insert_code_scan_run,
    list_code_hit_reviews,
    list_code_hit_snapshots,
    list_code_hits,
    list_code_scan_runs,
    list_code_watch_terms,
    list_code_watchlists,
    replace_code_watch_terms,
    update_code_hit_last_snapshot,
    upsert_code_hit,
    upsert_code_watchlist,
)
from darkweb_collector.document_exposure_browser import fetch_page_artifacts_with_session
from darkweb_collector.document_exposure_platforms import PLATFORMS, ExposurePlatform, get_exposure_platform
from darkweb_collector.document_exposure_sessions import build_platform_session_payloads, platform_storage_state_path
from darkweb_collector.runtime import output_root
from darkweb_collector.utils import dump_json, dump_text, safe_stem


logger = logging.getLogger("darkweb_collector.code_monitoring")
SHANGHAI_TZ = timezone(timedelta(hours=8))

DEFAULT_CODE_PLATFORMS = ["github", "gitlab", "gitee"]
DEFAULT_FILE_EXTENSIONS = ["env", "yaml", "yml", "json", "ini", "conf", "properties", "py", "js", "ts", "java"]
LEGACY_NARROW_FILE_EXTENSIONS = ["env", "yaml", "yml", "json"]
DEFAULT_SEARCH_PAGE_LIMIT = 3
DEFAULT_RULE_KEYS = [
    "api_key",
    "token",
    "ak_sk",
    "db_url",
    "jwt_secret",
    "redis_url",
    "private_key",
    "internal_url",
    "password",
]
DEFAULT_CODE_TERMS = [
    {"term": "示例企业", "term_type": "company_name", "weight": 0, "enabled": True},
    {"term": "example.com", "term_type": "domain", "weight": 0, "enabled": True},
]
SEARCH_URL_TEMPLATES = {
    "github": "https://github.com/search?q={query}&type=code",
    "gitlab": "https://gitlab.com/search?search={query}&nav_source=navbar&type=blobs",
    "gitee": "https://search.gitee.com/?skin=rec&type=code&q={query}",
}
GITEE_WIDGET_API_BASE = "https://so.gitee.com/v1"
GITEE_REPO_SEARCH_WIDGET = "wong1slagnlmzwvsu5ya"
REPO_FALLBACK_FILE_EXTENSIONS = [
    "env", "yaml", "yml", "json", "ini", "conf", "properties",
    "py", "js", "ts", "java", "go", "rb", "php", "sh", "toml", "xml", "txt", "csv",
]
CODE_CLUE_RULE_KEY = "clue"
CODE_CLUE_RULE_LABEL = "关键词线索"
CLUE_MARKERS: tuple[tuple[str, int], ...] = (
    ("password", 9),
    ("passwd", 9),
    ("pwd", 8),
    ("token", 8),
    ("secret", 8),
    ("apikey", 8),
    ("api_key", 8),
    ("jwt", 7),
    ("redis", 7),
    ("database", 6),
    ("db_host", 6),
    ("smtp", 6),
    ("mail", 5),
    ("auth", 5),
    ("login", 4),
    ("credential", 7),
    ("dotenv", 6),
    ("os.getenv", 7),
    ("process.env", 7),
)


@dataclass(frozen=True)
class SensitiveRule:
    key: str
    label: str
    pattern: re.Pattern[str]
    weight: int
    secret_like: bool = False


SENSITIVE_RULES: tuple[SensitiveRule, ...] = (
    SensitiveRule("api_key", "API Key", re.compile(r"(?i)(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"), 26, True),
    SensitiveRule("token", "访问 Token", re.compile(r"(?i)(?:token|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{12,}"), 24, True),
    SensitiveRule("ak_sk", "AK/SK", re.compile(r"(?i)(?:access[_-]?key|secret[_-]?key|app[_-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9/\+=_\-]{12,}"), 28, True),
    SensitiveRule("db_url", "数据库连接串", re.compile(r"(?i)(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?):\/\/[^\s'\"<>]{8,}"), 22, True),
    SensitiveRule("jwt_secret", "JWT Secret", re.compile(r"(?i)jwt[_-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-\/\+=]{8,}"), 24, True),
    SensitiveRule("redis_url", "Redis URL", re.compile(r"(?i)redis:\/\/[^\s'\"<>]{6,}"), 18, True),
    SensitiveRule("private_key", "私钥", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), 35, True),
    SensitiveRule("internal_url", "内网地址", re.compile(r"(?i)https?:\/\/(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|127\.0\.0\.1|localhost)[^\s'\"<>]*"), 16, False),
    SensitiveRule("password", "账号口令", re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"<>]{4,}"), 20, True),
)
SENSITIVE_RULE_MAP = {item.key: item for item in SENSITIVE_RULES}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()


def _strip_html(value: str) -> str:
    return _normalize_text(re.sub(r"<[^>]+>", " ", unescape(str(value or ""))))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _watchlist_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _parse_json((payload or {}).get("metadata_json"), {})
    return data if isinstance(data, dict) else {}


def _normalize_string_list(value: Any, *, lower: bool = False, fallback: list[str] | None = None) -> list[str]:
    items = _parse_json(value, value)
    if isinstance(items, str):
        items = [part.strip() for part in items.split(",")]
    if not isinstance(items, list):
        items = []
    seen: set[str] = set()
    rows: list[str] = []
    for item in items:
        normalized = _normalize_text(item)
        if lower:
            normalized = normalized.lower().lstrip(".")
        if normalized and normalized not in seen:
            seen.add(normalized)
            rows.append(normalized)
    return rows or list(fallback or [])


def _normalize_code_file_extensions(value: Any) -> list[str]:
    extensions = _normalize_string_list(value, lower=True, fallback=DEFAULT_FILE_EXTENSIONS)
    if extensions == LEGACY_NARROW_FILE_EXTENSIONS:
        return list(DEFAULT_FILE_EXTENSIONS)
    return extensions


def _normalize_search_page_limit(value: Any) -> int:
    try:
        limit = int(value or DEFAULT_SEARCH_PAGE_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_SEARCH_PAGE_LIMIT
    return max(1, min(limit, 10))


def _code_output_root() -> Path:
    path = output_root() / "code_monitoring"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _query_output_dir(watchlist_name: str, platform_key: str, term: str) -> Path:
    base = _code_output_root() / safe_stem(watchlist_name, "watchlist") / safe_stem(platform_key, "platform") / safe_stem(term, "term")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _public_output_url(path: Path) -> str:
    base = output_root().resolve()
    try:
        relative = path.resolve().relative_to(base)
    except ValueError:
        return path.resolve().as_uri()
    return f"/collector-output/{relative.as_posix()}"


def _load_storage_state_path(platform_key: str) -> str | None:
    rows = {row["platform"]: row for row in build_platform_session_payloads(module="code_monitoring")}
    row = rows.get(platform_key)
    if not row or not row.get("configured"):
        return None
    path = platform_storage_state_path(platform_key)
    return str(path) if path.exists() else None


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str]] = []
        self._in_script = False
        self._current_href = ""
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._in_script = True
            return
        if self._in_script:
            return
        if tag == "a":
            attr_map = dict(attrs)
            self._current_href = str(attr_map.get("href") or "")
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._in_script = False
            return
        if self._in_script:
            return
        if tag == "a":
            href = _normalize_text(self._current_href)
            text = _normalize_text("".join(self._current_text))
            if href:
                self.anchors.append({"href": href, "text": text})
            self._current_href = ""
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            return
        text = _normalize_text(data)
        if text and self._current_href:
            self._current_text.append(text)


def _platform_label(platform_key: str) -> str:
    return get_exposure_platform(platform_key).label if platform_key in PLATFORMS else platform_key


def _parse_line_range(fragment: str) -> tuple[int, int]:
    text = str(fragment or "").lstrip("#")
    match = re.search(r"L(\d+)(?:-L?(\d+))?", text, re.IGNORECASE)
    if not match:
        return 0, 0
    start = int(match.group(1))
    end = int(match.group(2) or start)
    return start, end


def _parse_code_location(platform_key: str, absolute_url: str) -> dict[str, Any] | None:
    parsed = urlparse(absolute_url)
    path = parsed.path.strip("/")
    if not path:
        return None
    if platform_key == "github":
        parts = path.split("/")
        if len(parts) < 5 or parts[2] != "blob":
            return None
        owner, repo, _, branch = parts[:4]
        file_path = "/".join(parts[4:])
        line_start, line_end = _parse_line_range(parsed.fragment)
        return {
            "repository_owner": owner,
            "repository_name": repo,
            "repository_url": f"{parsed.scheme}://{parsed.netloc}/{owner}/{repo}",
            "branch": branch,
            "file_path": file_path,
            "line_start": line_start,
            "line_end": line_end,
        }
    if platform_key == "gitee":
        parts = path.split("/")
        if len(parts) < 5 or parts[2] != "blob":
            return None
        owner, repo, _, branch = parts[:4]
        file_path = "/".join(parts[4:])
        line_start, line_end = _parse_line_range(parsed.fragment)
        return {
            "repository_owner": owner,
            "repository_name": repo,
            "repository_url": f"{parsed.scheme}://{parsed.netloc}/{owner}/{repo}",
            "branch": branch,
            "file_path": file_path,
            "line_start": line_start,
            "line_end": line_end,
        }
    if platform_key == "gitlab":
        if "/-/blob/" not in path:
            return None
        repo_path, blob_path = path.split("/-/blob/", 1)
        repo_parts = [part for part in repo_path.split("/") if part]
        blob_parts = [part for part in blob_path.split("/") if part]
        if len(repo_parts) < 2 or len(blob_parts) < 2:
            return None
        line_start, line_end = _parse_line_range(parsed.fragment)
        return {
            "repository_owner": "/".join(repo_parts[:-1]),
            "repository_name": repo_parts[-1],
            "repository_url": f"{parsed.scheme}://{parsed.netloc}/{repo_path}",
            "branch": blob_parts[0],
            "file_path": "/".join(blob_parts[1:]),
            "line_start": line_start,
            "line_end": line_end,
        }
    return None


def _raw_file_url(platform_key: str, absolute_url: str) -> str:
    parsed = urlparse(absolute_url)
    path = parsed.path.strip("/")
    if platform_key == "github":
        parts = path.split("/")
        if len(parts) >= 5 and parts[2] == "blob":
            owner, repo = parts[0], parts[1]
            branch = parts[3]
            file_path = "/".join(parts[4:])
            return f"{parsed.scheme}://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
    if platform_key == "gitlab" and "/-/blob/" in path:
        return f"{parsed.scheme}://{parsed.netloc}/{path.replace('/-/blob/', '/-/raw/', 1)}"
    if platform_key == "gitee":
        parts = path.split("/")
        if len(parts) >= 5 and parts[2] == "blob":
            owner, repo = parts[0], parts[1]
            branch = parts[3]
            file_path = "/".join(parts[4:])
            return f"{parsed.scheme}://{parsed.netloc}/{owner}/{repo}/raw/{branch}/{file_path}"
    return absolute_url


def _language_from_path(file_path: str) -> str:
    suffix = Path(file_path or "").suffix.lower()
    mapping = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".java": "Java",
        ".go": "Go",
        ".rb": "Ruby",
        ".php": "PHP",
        ".sh": "Shell",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".json": "JSON",
        ".env": "ENV",
        ".properties": "Properties",
        ".ini": "INI",
        ".conf": "Config",
    }
    return mapping.get(suffix, suffix.lstrip(".").upper())


def _matches_extension(file_path: str, extensions: list[str]) -> bool:
    if not extensions:
        return True
    file_name = Path(file_path or "").name.lower()
    suffix = Path(file_path or "").suffix.lower().lstrip(".")
    if not suffix and file_name.startswith(".env"):
        suffix = "env"
    return bool(suffix and suffix in {item.lower().lstrip(".") for item in extensions})


def _repo_fallback_extensions(extensions: list[str]) -> list[str]:
    normalized = []
    seen: set[str] = set()
    for item in [*(extensions or []), *DEFAULT_FILE_EXTENSIONS, *REPO_FALLBACK_FILE_EXTENSIONS]:
        value = _normalize_text(item).lower().lstrip(".")
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _candidate_priority(candidate: dict[str, Any], enabled_rule_keys: list[str]) -> int:
    file_path = str(candidate.get("filePath") or "").lower()
    snippet_text = str(candidate.get("snippetText") or "")
    hint_score = int(candidate.get("riskScoreHint") or 0)
    score = 0
    if file_path.endswith(".env") or "/.env" in file_path:
        score += 80
    elif file_path.endswith((".yaml", ".yml", ".ini", ".conf", ".properties")):
        score += 45
    elif file_path.endswith((".json", ".py", ".js", ".ts", ".java")):
        score += 20
    findings = _collect_findings(snippet_text, enabled_rule_keys)
    score += len(findings) * 120
    if snippet_text:
        lowered = snippet_text.lower()
        for marker in ("password", "secret", "token", "redis://", "db_host", "aws_secret_access_key", "jwt"):
            if marker in lowered:
                score += 25
    return max(score, hint_score)


def _file_path_priority(file_path: str) -> int:
    lowered = str(file_path or "").lower()
    score = 0
    if lowered.endswith(".env") or "/.env" in lowered:
        score += 90
    elif lowered.endswith((".yaml", ".yml", ".ini", ".conf", ".properties", ".toml", ".json", ".xml")):
        score += 50
    elif lowered.endswith((".py", ".js", ".ts", ".java", ".go", ".rb", ".php", ".sh")):
        score += 20
    for marker in ("secret", "token", "password", "credential", "config", "setting", "redis", "jwt", "db", "auth", "prod"):
        if marker in lowered:
            score += 12
    return score


def _search_url(platform_key: str, term: str) -> str:
    template = SEARCH_URL_TEMPLATES.get(platform_key)
    if not template:
        raise ValueError(f"search URL template not configured for platform: {platform_key}")
    return template.format(query=quote_plus(term))


def _search_markers(enabled_rule_keys: list[str]) -> list[str]:
    marker_map = {
        "api_key": "api key",
        "token": "token",
        "ak_sk": "secret key",
        "db_url": "database",
        "jwt_secret": "jwt",
        "redis_url": "redis",
        "private_key": "private key",
        "internal_url": "internal url",
        "password": "password",
    }
    markers = []
    seen: set[str] = set()
    for key in enabled_rule_keys:
        marker = marker_map.get(str(key or "").strip())
        if marker and marker not in seen:
            seen.add(marker)
            markers.append(marker)
    return markers


def _expanded_search_queries(term: str, enabled_rule_keys: list[str]) -> list[str]:
    normalized = _normalize_text(term)
    if not normalized:
        return []
    queries: list[str] = []
    seen: set[str] = set()

    def add_query(value: str) -> None:
        text = _normalize_text(value)
        if text and text not in seen:
            seen.add(text)
            queries.append(text)

    domain_like = "." in normalized and " " not in normalized
    if domain_like:
        add_query(f"@{normalized.lower()}")
    for marker in _search_markers(enabled_rule_keys)[:4]:
        add_query(f"{normalized} {marker}")
        if domain_like:
            add_query(f"@{normalized.lower()} {marker}")
    return queries[:8]


def _search_page_url(platform_key: str, search_url: str, page: int) -> str:
    if page <= 1:
        return search_url
    parsed = urlparse(search_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if platform_key == "github":
        query["p"] = str(page)
    elif platform_key == "gitlab":
        query["page"] = str(page)
    elif platform_key == "gitee":
        query["page"] = str(page)
    else:
        return search_url
    return urlunparse(parsed._replace(query=urlencode(query)))


def _parse_code_search_results(platform: ExposurePlatform, html: str, requested_url: str) -> list[dict[str, Any]]:
    parser = _AnchorParser()
    parser.feed(html)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parser.anchors:
        absolute = urljoin(requested_url, item["href"])
        location = _parse_code_location(platform.key, absolute)
        if location is not None:
            dedupe_key = f"{platform.key}|{location['repository_url']}|{location['branch']}|{location['file_path']}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(
                {
                    "platform": platform.key,
                    "platformLabel": platform.label,
                    "fileUrl": absolute,
                    "title": _normalize_text(item.get("text")) or location["file_path"] or absolute,
                    "repositoryOwner": location["repository_owner"],
                    "repositoryName": location["repository_name"],
                    "repositoryUrl": location["repository_url"],
                    "branch": location["branch"],
                    "filePath": location["file_path"],
                    "lineStart": location["line_start"],
                    "lineEnd": location["line_end"],
                }
            )
            continue
        if platform.key == "gitlab":
            parsed = urlparse(absolute)
            path = parsed.path.strip("/")
            parts = [part for part in path.split("/") if part]
            excluded_roots = {"projects", "groups", "dashboard", "help", "users", "explore", "admin", "-"}
            if (
                len(parts) >= 2
                and parts[0] not in excluded_roots
                and "/users/" not in absolute
                and "/search?" not in absolute
                and "/-/" not in absolute
            ):
                repo_owner = "/".join(parts[:-1])
                repo_name = parts[-1]
                dedupe_key = f"gitlab-project|{repo_owner}|{repo_name}"
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                results.append(
                    {
                        "platform": platform.key,
                        "platformLabel": platform.label,
                        "fileUrl": absolute,
                        "title": _normalize_text(item.get("text")) or repo_name,
                        "repositoryOwner": repo_owner,
                        "repositoryName": repo_name,
                        "repositoryUrl": f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts)}",
                        "branch": "",
                        "filePath": "",
                        "lineStart": 0,
                        "lineEnd": 0,
                    }
                )
    return results


def _build_gitlab_project_code_search_url(repository_url: str, term: str) -> str:
    base = repository_url.rstrip("/")
    return f"{base}/-/search?search={quote_plus(term)}&nav_source=navbar&project_id=&scope=blobs&search_code=true"


def _cookie_header_from_storage_state(storage_state_path: str | None, domain_fragment: str) -> str:
    if not storage_state_path:
        return ""
    path = Path(storage_state_path)
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    cookies = []
    for item in payload.get("cookies", []):
        domain = str(item.get("domain") or "")
        if domain_fragment in domain and item.get("name") and item.get("value"):
            cookies.append(f"{item['name']}={item['value']}")
    return "; ".join(cookies)


def _http_get_json(url: str, *, headers: dict[str, str], timeout: int = 60) -> Any:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        text = response.read().decode("utf-8", errors="replace")
    return json.loads(text)


def _http_get_html(url: str, *, headers: dict[str, str], timeout: int = 60) -> str:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _search_request_headers(platform_key: str, storage_state_path: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    domain_fragment = {
        "github": "github.com",
        "gitlab": "gitlab.com",
        "gitee": "gitee.com",
    }.get(platform_key, "")
    if domain_fragment:
        cookie_header = _cookie_header_from_storage_state(storage_state_path, domain_fragment)
        if cookie_header:
            headers["Cookie"] = cookie_header
    referer = {
        "github": "https://github.com/search",
        "gitlab": "https://gitlab.com/search",
        "gitee": "https://search.gitee.com/",
    }.get(platform_key)
    if referer:
        headers["Referer"] = referer
    return headers


def _gitlab_project_blob_search(repository_url: str, term: str, storage_state_path: str | None) -> list[dict[str, Any]]:
    parsed = urlparse(repository_url)
    repo_path = parsed.path.strip("/")
    parts = [part for part in repo_path.split("/") if part]
    if len(parts) < 2:
        return []
    cookie_header = _cookie_header_from_storage_state(storage_state_path, "gitlab.com")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    encoded_project = quote_plus(repo_path)
    api_url = f"https://gitlab.com/api/v4/projects/{encoded_project}/search?scope=blobs&search={quote_plus(term)}"
    rows = _http_get_json(api_url, headers=headers, timeout=60)
    if not isinstance(rows, list):
        return []
    repository_owner = "/".join(parts[:-1])
    repository_name = parts[-1]
    results: list[dict[str, Any]] = []
    for row in rows:
        file_path = _normalize_text(row.get("path"))
        ref = _normalize_text(row.get("ref")) or "main"
        start_line = int(row.get("startline") or 0)
        if not file_path:
            continue
        file_url = f"{parsed.scheme}://{parsed.netloc}/{repo_path}/-/blob/{ref}/{file_path}"
        if start_line:
            file_url = f"{file_url}#L{start_line}"
        results.append(
            {
                "platform": "gitlab",
                "platformLabel": "GitLab",
                "fileUrl": file_url,
                "title": _normalize_text(row.get("filename") or file_path),
                "repositoryOwner": repository_owner,
                "repositoryName": repository_name,
                "repositoryUrl": f"{parsed.scheme}://{parsed.netloc}/{repo_path}",
                "branch": ref,
                "filePath": file_path,
                "lineStart": start_line,
                "lineEnd": start_line,
                "snippetText": str(row.get("data") or ""),
            }
        )
    return results


def _gitlab_repo_search(term: str, page_limit: int = 1) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, max(1, page_limit) + 1):
        url = f"https://gitlab.com/api/v4/projects?search={quote_plus(term)}&simple=true&per_page=10&order_by=last_activity_at&sort=desc&page={page}"
        rows = _http_get_json(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
            timeout=60,
        )
        if not isinstance(rows, list) or not rows:
            break
        new_count = 0
        for item in rows:
            repo_url = _normalize_text(item.get("web_url"))
            path_with_namespace = _normalize_text(item.get("path_with_namespace"))
            if not repo_url or not path_with_namespace or "/" not in path_with_namespace or repo_url in seen:
                continue
            seen.add(repo_url)
            parts = path_with_namespace.split("/")
            results.append(
                {
                    "platform": "gitlab",
                    "platformLabel": "GitLab",
                    "repositoryOwner": "/".join(parts[:-1]),
                    "repositoryName": parts[-1],
                    "repositoryUrl": repo_url,
                }
            )
            new_count += 1
        if new_count == 0:
            break
    return results


def _gitlab_repo_fallback_code_search(
    term: str,
    storage_state_path: str | None,
    extensions: list[str],
    max_results: int,
    page_limit: int = 1,
) -> list[dict[str, Any]]:
    repos = _gitlab_repo_search(term, page_limit=page_limit)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for repo in repos[: min(6, max_results or 6)]:
        try:
            nested_candidates = _gitlab_project_blob_search(repo["repositoryUrl"], term, storage_state_path)
        except Exception:
            continue
        for item in nested_candidates:
            file_path = str(item.get("filePath") or "")
            key = f"{item.get('repositoryUrl')}|{item.get('branch')}|{file_path}"
            if key in seen or not _matches_extension(file_path, extensions):
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= max_results:
                return results
    return results


def _github_repo_search(term: str, page_limit: int = 1) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, max(1, page_limit) + 1):
        url = f"https://api.github.com/search/repositories?q={quote_plus(term)}&per_page=8&page={page}"
        payload = _http_get_json(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/vnd.github+json",
            },
            timeout=60,
        )
        items = (payload or {}).get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            break
        new_count = 0
        for item in items:
            repo_url = _normalize_text(item.get("html_url"))
            owner = _normalize_text(((item.get("owner") or {}) if isinstance(item.get("owner"), dict) else {}).get("login"))
            repo_name = _normalize_text(item.get("name"))
            default_branch = _normalize_text(item.get("default_branch")) or "main"
            if not repo_url or not owner or not repo_name or repo_url in seen:
                continue
            seen.add(repo_url)
            results.append(
                {
                    "platform": "github",
                    "platformLabel": "GitHub",
                    "repositoryOwner": owner,
                    "repositoryName": repo_name,
                    "repositoryUrl": repo_url,
                    "branch": default_branch,
                }
            )
            new_count += 1
        if new_count == 0:
            break
    return results


def _github_repo_default_branch(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{quote_plus(owner)}/{quote_plus(repo)}"
    payload = _http_get_json(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.github+json",
        },
        timeout=60,
    )
    if not isinstance(payload, dict):
        return "main"
    return _normalize_text(payload.get("default_branch")) or "main"


def _github_repo_tree(owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{quote_plus(owner)}/{quote_plus(repo)}/git/trees/{quote_plus(branch)}?recursive=1"
    payload = _http_get_json(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.github+json",
        },
        timeout=60,
    )
    tree = (payload or {}).get("tree") if isinstance(payload, dict) else None
    return tree if isinstance(tree, list) else []


def _http_get_text(url: str, *, headers: dict[str, str], timeout: int = 60) -> str:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _github_blob_content(owner: str, repo: str, branch: str, file_path: str) -> str:
    encoded_path = "/".join(quote_plus(part) for part in str(file_path or "").split("/"))
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{encoded_path}"
    try:
        return _http_get_text(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/plain",
            },
            timeout=45,
        )
    except Exception:
        return ""


def _github_repo_fallback_code_search(
    term: str,
    extensions: list[str],
    enabled_rule_keys: list[str],
    max_results: int,
    page_limit: int = 1,
) -> list[dict[str, Any]]:
    repos = _github_repo_search(term, page_limit=page_limit)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    fallback_extensions = _repo_fallback_extensions(extensions)
    for repo in repos[: min(5, max_results or 5)]:
        owner = _normalize_text(repo.get("repositoryOwner"))
        repo_name = _normalize_text(repo.get("repositoryName"))
        repo_url = _normalize_text(repo.get("repositoryUrl"))
        if not owner or not repo_name or not repo_url:
            continue
        branch = _normalize_text(repo.get("branch")) or _github_repo_default_branch(owner, repo_name)
        try:
            tree = _github_repo_tree(owner, repo_name, branch)
        except Exception:
            continue
        candidate_paths = []
        for item in tree:
            file_path = _normalize_text(item.get("path"))
            if item.get("type") != "blob" or not _matches_extension(file_path, fallback_extensions):
                continue
            candidate_paths.append((_file_path_priority(file_path), file_path))
        candidate_paths.sort(key=lambda row: (row[0], row[1]), reverse=True)
        for _, file_path in candidate_paths[:30]:
            key = f"{repo_url}|{branch}|{file_path}"
            if key in seen:
                continue
            code_text = _github_blob_content(owner, repo_name, branch, file_path)
            if not code_text:
                continue
            classification = _classify_code_hit(term, file_path, code_text, enabled_rule_keys)
            if not classification:
                continue
            candidate = {
                "platform": "github",
                "platformLabel": "GitHub",
                "fileUrl": f"https://github.com/{owner}/{repo_name}/blob/{branch}/{file_path}",
                "title": file_path,
                "repositoryOwner": owner,
                "repositoryName": repo_name,
                "repositoryUrl": repo_url,
                "branch": branch,
                "filePath": file_path,
                "lineStart": 0,
                "lineEnd": 0,
                "snippetText": code_text[:1200],
                "resultLayerHint": classification["result_layer"],
                "riskScoreHint": classification["risk_score"],
                "severityHint": classification["severity"],
            }
            seen.add(key)
            results.append(candidate)
            if len(results) >= max_results:
                return results
    return results


def _gitee_repo_search(term: str, page_limit: int = 1) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    size = 20
    for page in range(1, max(1, page_limit) + 1):
        from_offset = (page - 1) * size
        url = f"{GITEE_WIDGET_API_BASE}/search/widget/{GITEE_REPO_SEARCH_WIDGET}?q={quote_plus(term)}&from={from_offset}&size={size}"
        rows = _http_get_json(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://search.gitee.com/",
            },
            timeout=60,
        )
        hits = (((rows or {}).get("hits") or {}).get("hits") or []) if isinstance(rows, dict) else []
        if not hits:
            break
        new_count = 0
        for item in hits:
            fields = item.get("fields") or {}
            repo_url = _normalize_text((fields.get("url") or [""])[0])
            title = _normalize_text((fields.get("title") or [""])[0])
            path_name = _normalize_text((fields.get("path") or [""])[0])
            owner_path = _normalize_text((fields.get("owner.path.keyword") or [""])[0])
            if not repo_url or not owner_path or not path_name or repo_url in seen:
                continue
            seen.add(repo_url)
            results.append(
                {
                    "platform": "gitee",
                    "platformLabel": "Gitee",
                    "fileUrl": repo_url,
                    "title": title or path_name,
                    "repositoryOwner": owner_path,
                    "repositoryName": path_name,
                    "repositoryUrl": repo_url,
                    "branch": "",
                    "filePath": "",
                    "lineStart": 0,
                    "lineEnd": 0,
                    "snippetText": _normalize_text((fields.get("description") or [""])[0]),
                }
            )
            new_count += 1
        if new_count == 0:
            break
    return results


def _gitee_repo_default_branch(owner: str, repo: str) -> str:
    url = f"https://gitee.com/api/v5/repos/{owner}/{repo}"
    payload = _http_get_json(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=60)
    if not isinstance(payload, dict):
        return "master"
    return _normalize_text(payload.get("default_branch")) or "master"


def _gitee_repo_tree(owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
    url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/git/trees/{quote_plus(branch)}?recursive=1"
    payload = _http_get_json(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=60)
    if not isinstance(payload, dict):
        return []
    tree = payload.get("tree") or []
    return tree if isinstance(tree, list) else []


def _gitee_blob_content(owner: str, repo: str, branch: str, file_path: str) -> str:
    encoded_path = "/".join(quote_plus(part) for part in file_path.split("/"))
    url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{encoded_path}?ref={quote_plus(branch)}"
    payload = _http_get_json(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=60)
    if isinstance(payload, dict):
        if payload.get("type") == "file" and payload.get("encoding") == "base64" and payload.get("content"):
            try:
                return base64.b64decode(str(payload["content"])).decode("utf-8", errors="replace")
            except Exception:
                return ""
    return ""


def _gitee_repo_code_search(term: str, extensions: list[str], enabled_rule_keys: list[str], page_limit: int = 1) -> list[dict[str, Any]]:
    repo_candidates = _gitee_repo_search(term, page_limit=page_limit)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for repo_candidate in repo_candidates:
        owner = _normalize_text(repo_candidate.get("repositoryOwner"))
        repo = _normalize_text(repo_candidate.get("repositoryName"))
        repo_url = _normalize_text(repo_candidate.get("repositoryUrl"))
        if not owner or not repo or not repo_url:
            continue
        try:
            branch = _gitee_repo_default_branch(owner, repo)
            tree = _gitee_repo_tree(owner, repo, branch)
        except Exception:
            continue
        for item in tree:
            file_path = _normalize_text(item.get("path"))
            if item.get("type") != "blob" or not _matches_extension(file_path, extensions):
                continue
            dedupe_key = f"{repo_url}|{branch}|{file_path}"
            if dedupe_key in seen:
                continue
            try:
                code_text = _gitee_blob_content(owner, repo, branch, file_path)
            except Exception:
                code_text = ""
            if not code_text:
                continue
            classification = _classify_code_hit(term, file_path, code_text, enabled_rule_keys)
            if not classification:
                continue
            seen.add(dedupe_key)
            file_url = f"https://gitee.com/{owner}/{repo}/blob/{branch}/{file_path}"
            results.append(
                {
                    "platform": "gitee",
                    "platformLabel": "Gitee",
                    "fileUrl": file_url,
                    "title": file_path,
                    "repositoryOwner": owner,
                    "repositoryName": repo,
                    "repositoryUrl": repo_url,
                    "branch": branch,
                    "filePath": file_path,
                    "lineStart": 0,
                    "lineEnd": 0,
                    "snippetText": code_text[:1200],
                    "resultLayerHint": classification["result_layer"],
                    "riskScoreHint": classification["risk_score"],
                    "severityHint": classification["severity"],
                }
            )
    results.sort(key=lambda item: _candidate_priority(item, enabled_rule_keys), reverse=True)
    return results


def _detect_code_search_issue(platform: ExposurePlatform, html: str, page_url: str, page_title: str) -> str:
    lowered = f"{html}\n{page_url}\n{page_title}".lower()
    challenge_signals = (
        "安全验证码" in html
        or "安全验证" in html
        or "verify you are human" in lowered
        or "cf-challenge" in lowered
        or "please move your mouse or press a key" in lowered
        or "please wait while we verify" in lowered
        or "just a moment" in lowered
    )
    if challenge_signals:
        return f"{platform.key}:captcha_or_security_verification"
    if "/users/sign_in" in lowered or "just a moment" in lowered or "cf-challenge" in lowered:
        return f"{platform.key}:login_or_challenge_required"
    if any(token.lower() in lowered for token in platform.login_indicators) or "sign in" in lowered:
        return f"{platform.key}:login_required"
    if "too many requests" in lowered or "rate limit" in lowered:
        return f"{platform.key}:rate_limited"
    return ""


def _extract_code_text(html: str) -> str:
    selectors = [
        r"<div[^>]*id=\"LC\d+\"[^>]*>(.*?)</div>",
        r"<td[^>]*class=\"[^\"]*(?:blob-code|code-content|line_content)[^\"]*\"[^>]*>(.*?)</td>",
        r"<span[^>]*id=\"LC\d+\"[^>]*>(.*?)</span>",
        r"<pre[^>]*>(.*?)</pre>",
        r"<code[^>]*>(.*?)</code>",
    ]
    for pattern in selectors:
        chunks = re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        cleaned = [_strip_html(chunk) for chunk in chunks if _strip_html(chunk)]
        if cleaned:
            return "\n".join(cleaned)
    return _strip_html(html)


def _extract_code_lines(html: str) -> list[tuple[int, str]]:
    line_patterns = [
        r"<div[^>]*id=\"LC(\d+)\"[^>]*>(.*?)</div>",
        r"<td[^>]*data-line-number=\"(\d+)\"[^>]*>.*?</td>\s*<td[^>]*class=\"[^\"]*(?:blob-code|code-content|line_content)[^\"]*\"[^>]*>(.*?)</td>",
    ]
    for pattern in line_patterns:
        matches = re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        rows: list[tuple[int, str]] = []
        for line_no, chunk in matches:
            cleaned = _strip_html(chunk)
            if cleaned:
                rows.append((int(line_no), cleaned))
        if rows:
            return rows
    code_text = _extract_code_text(html)
    if not code_text:
        return []
    return [(index + 1, line) for index, line in enumerate(code_text.splitlines()) if line.strip()]


def _read_text_file(path_value: Any) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _build_code_lines_from_text(code_text: str) -> list[tuple[int, str]]:
    return [(index + 1, line.rstrip()) for index, line in enumerate(str(code_text or "").splitlines()) if line.strip()]


def _load_snapshot_code_lines(latest_snapshot: dict[str, Any], raw_payload: dict[str, Any]) -> list[tuple[int, str]]:
    candidate = raw_payload.get("candidate") if isinstance(raw_payload, dict) else {}
    candidate = candidate if isinstance(candidate, dict) else {}
    html_text = _read_text_file(latest_snapshot.get("htmlPath"))
    code_lines = _extract_code_lines(html_text) if html_text else []
    if code_lines:
        return code_lines
    artifact_payload = _parse_json(_read_text_file(latest_snapshot.get("rawArtifactPath")), {})
    if isinstance(artifact_payload, dict):
        code_text = str(
            artifact_payload.get("code_text")
            or ((artifact_payload.get("candidate") or {}) if isinstance(artifact_payload.get("candidate"), dict) else {}).get("snippetText")
            or ""
        )
        if code_text:
            return _build_code_lines_from_text(code_text)
    code_text = str(candidate.get("snippetText") or "")
    if code_text:
        return _build_code_lines_from_text(code_text)
    return []


def _line_window(code_lines: list[tuple[int, str]], start_line: int, end_line: int, *, before: int = 1, after: int = 1) -> tuple[str, int, int]:
    if not code_lines:
        return "", 0, 0
    indexes = [index for index, (line_no, _) in enumerate(code_lines) if start_line <= line_no <= max(start_line, end_line)]
    if not indexes:
        return "", 0, 0
    start_index = max(0, min(indexes) - before)
    end_index = min(len(code_lines), max(indexes) + after + 1)
    return (
        "\n".join(text for _, text in code_lines[start_index:end_index]),
        code_lines[start_index][0],
        code_lines[end_index - 1][0],
    )


def _mask_preview_text(text: str, findings: list[dict[str, Any]]) -> str:
    masked = str(text or "")
    for finding in findings:
        value = str(finding.get("value") or "")
        if value:
            masked = masked.replace(value, _mask_value(value))
    return masked


def _line_match_score(line_text: str, probe: str) -> int:
    normalized_line = re.sub(r"\s+", "", str(line_text or "")).lower()
    normalized_probe = re.sub(r"\s+", "", str(probe or "")).lower()
    if not normalized_line or not normalized_probe:
        return 0
    if normalized_probe in normalized_line:
        return len(normalized_probe)
    tokens = [token for token in re.split(r"[^a-z0-9_.@:/-]+", normalized_probe) if token]
    if not tokens:
        return 0
    return sum(len(token) for token in tokens if token in normalized_line)


def _find_finding_line_window(code_lines: list[tuple[int, str]], findings: list[dict[str, Any]], *, before: int = 8, after: int = 18) -> tuple[str, int, int]:
    if not code_lines or not findings:
        return "", 0, 0
    best_index = -1
    best_score = 0
    for finding in findings:
        probes = [str(finding.get("value") or "").strip(), str(finding.get("excerpt") or "").strip()]
        for index, (_, line_text) in enumerate(code_lines):
            score = max(_line_match_score(line_text, probe) for probe in probes if probe)
            if score > best_score:
                best_score = score
                best_index = index
    if best_index < 0:
        return "", 0, 0
    start_index = max(0, best_index - before)
    end_index = min(len(code_lines), best_index + after + 1)
    return (
        "\n".join(text for _, text in code_lines[start_index:end_index]),
        code_lines[start_index][0],
        code_lines[end_index - 1][0],
    )


def _rebuild_code_preview(matched_term: str, latest_snapshot: dict[str, Any], raw_payload: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    code_lines = _load_snapshot_code_lines(latest_snapshot, raw_payload)
    lowered_term = _normalize_text(matched_term).lower()
    snippet = ""
    if code_lines:
        snippet, _, _ = _find_finding_line_window(code_lines, findings, before=8, after=18)
        line_start = int(latest_snapshot.get("lineStart") or 0)
        line_end = int(latest_snapshot.get("lineEnd") or line_start)
        if line_start and not snippet:
            snippet, _, _ = _line_window(code_lines, line_start, line_end, before=1, after=1)
        if lowered_term and (not snippet or lowered_term not in snippet.lower()):
            for index, (line_no, line_text) in enumerate(code_lines):
                if lowered_term not in line_text.lower():
                    continue
                start_index = max(0, index - 6)
                end_index = min(len(code_lines), index + 10)
                snippet = "\n".join(text for _, text in code_lines[start_index:end_index])
                break
    if snippet:
        return _mask_preview_text(snippet, findings)
    return str(latest_snapshot.get("maskedFragment") or latest_snapshot.get("codeFragment") or "")


def _extract_matched_term_contexts(term: str, row: dict[str, Any], latest_snapshot: dict[str, Any], raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return []
    lowered_term = normalized_term.lower()
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_context(kind: str, label: str, text: str, *, line_start: int = 0, line_end: int = 0) -> None:
        lines = [part.rstrip() for part in str(text or "").splitlines()]
        display_text = "\n".join(lines).strip() if kind == "code" else _normalize_text(text)
        if not display_text:
            return
        key = f"{kind}|{label}|{line_start}|{line_end}|{display_text}"
        if key in seen:
            return
        seen.add(key)
        contexts.append(
            {
                "kind": kind,
                "label": label,
                "text": display_text,
                "lineStart": int(line_start or 0),
                "lineEnd": int(line_end or 0),
            }
        )

    candidate = raw_payload.get("candidate") if isinstance(raw_payload, dict) else {}
    candidate = candidate if isinstance(candidate, dict) else {}
    code_lines = _load_snapshot_code_lines(latest_snapshot, raw_payload)

    if code_lines:
        line_start = int(latest_snapshot.get("lineStart") or 0)
        line_end = int(latest_snapshot.get("lineEnd") or line_start)
        if line_start:
            window_text, context_start, context_end = _line_window(code_lines, line_start, line_end, before=1, after=1)
            if window_text and lowered_term in window_text.lower():
                add_context("code", "代码上下文", window_text, line_start=context_start, line_end=context_end)
        code_matches = 0
        for index, (_, line) in enumerate(code_lines):
            if lowered_term not in line.lower():
                continue
            start_index = max(0, index - 1)
            end_index = min(len(code_lines), index + 2)
            add_context(
                "code",
                "代码上下文",
                "\n".join(text for _, text in code_lines[start_index:end_index]),
                line_start=code_lines[start_index][0],
                line_end=code_lines[end_index - 1][0],
            )
            code_matches += 1
            if code_matches >= 3:
                break

    repository_full_name = "/".join(
        part for part in [row.get("repository_owner") or "", row.get("repository_name") or ""] if part
    )
    if lowered_term in repository_full_name.lower():
        add_context("repository", "仓库名", repository_full_name)
    if lowered_term in str(row.get("repository_url") or "").lower():
        add_context("repository_url", "仓库地址", str(row.get("repository_url") or ""))
    if lowered_term in str(row.get("file_path") or "").lower():
        add_context("file", "文件路径", str(row.get("file_path") or ""))
    if lowered_term in str(row.get("file_url") or "").lower():
        add_context("file_url", "文件地址", str(row.get("file_url") or ""))
    if lowered_term in str(candidate.get("title") or "").lower():
        add_context("title", "结果标题", str(candidate.get("title") or ""))

    return contexts


def _term_matches_context(term: str, candidate: dict[str, Any], code_text: str) -> bool:
    lowered = term.lower()
    haystack = " ".join(
        [
            str(candidate.get("repositoryOwner") or ""),
            str(candidate.get("repositoryName") or ""),
            str(candidate.get("filePath") or ""),
            str(candidate.get("title") or ""),
            code_text[:6000],
        ]
    ).lower()
    return lowered in haystack


def _collect_findings(code_text: str, enabled_rule_keys: list[str]) -> list[dict[str, Any]]:
    enabled = [SENSITIVE_RULE_MAP[key] for key in enabled_rule_keys if key in SENSITIVE_RULE_MAP]
    findings: list[dict[str, Any]] = []
    for rule in enabled:
        for match in rule.pattern.finditer(code_text):
            value = match.group(0)
            findings.append(
                {
                    "ruleKey": rule.key,
                    "label": rule.label,
                    "secretLike": rule.secret_like,
                    "weight": rule.weight,
                    "start": match.start(),
                    "end": match.end(),
                    "value": value,
                    "excerpt": _normalize_text(value)[:220],
                }
            )
            if len(findings) >= 12:
                return findings
    return findings


def _mask_value(value: str) -> str:
    text = str(value or "")
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}***{text[-4:]}"


def _extract_snippet(code_text: str, findings: list[dict[str, Any]]) -> str:
    if not code_text:
        return ""
    if not findings:
        return code_text[:800]
    start = max(0, int(findings[0]["start"]) - 260)
    end = min(len(code_text), int(findings[0]["end"]) + 260)
    return code_text[start:end]


def _mask_snippet(snippet: str, findings: list[dict[str, Any]]) -> str:
    masked = str(snippet or "")
    for finding in findings:
        value = str(finding.get("value") or "")
        if value:
            masked = masked.replace(value, _mask_value(value), 1)
    return masked


def _normalize_code_suffix(file_path: str) -> str:
    file_name = Path(file_path or "").name.lower()
    suffix = Path(file_path or "").suffix.lower()
    if not suffix and file_name.startswith(".env"):
        return ".env"
    return suffix


def _looks_literal_secret(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if "-----begin" in lowered and "private key-----" in lowered:
        return True
    if "://" in text:
        return True
    if re.search(r"[:=]\s*['\"][^'\"]{6,}['\"]", text):
        return True
    rhs_match = re.search(r"[:=]\s*([^\s].*)$", text)
    rhs = rhs_match.group(1).strip().rstrip(",") if rhs_match else text
    if "(" in rhs or ")" in rhs:
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", rhs):
        return False
    if re.fullmatch(r"[A-Za-z0-9_./+\-=:@]{16,}", rhs):
        return True
    return False


def _finding_signal_score(finding: dict[str, Any]) -> int:
    rule_weight = int(finding.get("weight") or 0)
    value = str(finding.get("value") or "")
    if _looks_literal_secret(value):
        return rule_weight + 16
    if "(" in value or ")" in value:
        return max(8, int(rule_weight * 0.45))
    return int(rule_weight * 0.7)


def _file_exposure_bonus(file_path: str) -> int:
    suffix = _normalize_code_suffix(file_path)
    if suffix == ".env":
        return 16
    if suffix in {".yaml", ".yml", ".ini", ".conf", ".properties"}:
        return 12
    if suffix == ".json":
        return 8
    if suffix in {".py", ".js", ".ts", ".java", ".go", ".rb", ".php", ".sh"}:
        return 5
    return 2


def _severity_from_score(score: int) -> str:
    if score >= 58:
        return "high"
    if score >= 32:
        return "medium"
    return "low"


def _file_exposure_label(file_path: str) -> str:
    suffix = _normalize_code_suffix(file_path)
    if suffix == ".env":
        return "环境变量文件"
    if suffix in {".yaml", ".yml", ".ini", ".conf", ".properties"}:
        return "配置文件"
    if suffix == ".json":
        return "结构化配置文件"
    if suffix in {".py", ".js", ".ts", ".java", ".go", ".rb", ".php", ".sh"}:
        return "源码文件"
    return "普通文本"


def _collect_clue_markers(term: str, code_text: str) -> list[str]:
    lowered = str(code_text or "").lower()
    markers: list[str] = []
    seen: set[str] = set()
    for marker, _score in CLUE_MARKERS:
        if marker in lowered and marker not in seen:
            seen.add(marker)
            markers.append(marker)
    normalized_term = _normalize_text(term).lower()
    if "." in normalized_term and f"@{normalized_term}" in lowered and f"@{normalized_term}" not in seen:
        markers.append(f"@{normalized_term}")
    return markers


def _score_clue_hit(term: str, file_path: str, code_text: str) -> tuple[int, str, list[str]]:
    markers = _collect_clue_markers(term, code_text)
    score = _file_exposure_bonus(file_path)
    if markers:
        score += min(28, sum(next((weight for key, weight in CLUE_MARKERS if key == marker), 10) for marker in markers[:4]))
    lowered_term = _normalize_text(term).lower()
    lowered_code = str(code_text or "").lower()
    if lowered_term and lowered_term in lowered_code:
        score += 12
    if "." in lowered_term and f"@{lowered_term}" in lowered_code:
        score += 12
    if "os.getenv" in lowered_code or "process.env" in lowered_code or "dotenv" in lowered_code:
        score += 8
    if "config" in lowered_code and "password" in lowered_code:
        score += 6
    score = min(score, 100)
    severity = _severity_from_score(score)
    return score, severity, markers


def _build_code_clue_reasons(matched_term: str, file_path: str, markers: list[str]) -> list[str]:
    reasons = [f"检索命中词：{matched_term or '-'}"]
    if markers:
        reasons.append(f"命中线索标记：{' / '.join(markers[:5])}")
    reasons.append(f"文件暴露面：{_file_exposure_label(file_path)}")
    reasons.append("当前为线索命中，尚未识别到明确敏感凭据或密钥。")
    return reasons


def _code_result_layer(sensitive_type: str, raw_payload: dict[str, Any] | None = None) -> str:
    payload_layer = _normalize_text((raw_payload or {}).get("result_layer"))
    if payload_layer in {"clue", "sensitive"}:
        return payload_layer
    return "clue" if str(sensitive_type or "").strip() == CODE_CLUE_RULE_KEY else "sensitive"


def _build_code_risk_reasons(matched_term: str, file_path: str, findings: list[dict[str, Any]]) -> list[str]:
    reasons = [f"检索命中词：{matched_term or '-'}"]
    if not findings:
        reasons.append("当前未提取到敏感规则命中。")
        return reasons
    unique_rules = []
    seen_rules: set[str] = set()
    for item in findings:
        rule_key = str(item.get("ruleKey") or "")
        label = str(item.get("label") or rule_key or "未知")
        if rule_key and rule_key not in seen_rules:
            seen_rules.add(rule_key)
            unique_rules.append(label)
    reasons.append(f"发现 {len(findings)} 处命中，涉及 {len(unique_rules)} 类敏感规则。")
    if unique_rules:
        reasons.append(f"敏感类型：{' / '.join(unique_rules[:4])}")
    if any(_looks_literal_secret(str(item.get('value') or '')) for item in findings):
        reasons.append("包含硬编码字面量、连接串或密钥材料，泄露确定性较高。")
    elif any(bool(item.get("secretLike")) for item in findings):
        reasons.append("存在敏感变量或凭据引用，需结合上下文复核是否为真实泄露。")
    reasons.append(f"文件暴露面：{_file_exposure_label(file_path)}")
    return reasons


def _classify_code_hit(term: str, file_path: str, code_text: str, enabled_rule_keys: list[str]) -> dict[str, Any] | None:
    findings = _collect_findings(code_text, enabled_rule_keys)
    if findings:
        risk_score, severity = _score_code_hit(file_path, findings)
        return {
            "result_layer": "sensitive",
            "sensitive_type": findings[0]["ruleKey"],
            "matched_rule": findings[0]["label"],
            "risk_score": risk_score,
            "severity": severity,
            "findings": findings,
            "clue_markers": [],
        }
    clue_score, clue_severity, clue_markers = _score_clue_hit(term, file_path, code_text)
    if clue_score < 28:
        return None
    return {
        "result_layer": "clue",
        "sensitive_type": CODE_CLUE_RULE_KEY,
        "matched_rule": CODE_CLUE_RULE_LABEL,
        "risk_score": clue_score,
        "severity": clue_severity,
        "findings": [],
        "clue_markers": clue_markers,
    }


def _score_code_hit(file_path: str, findings: list[dict[str, Any]]) -> tuple[int, str]:
    if not findings:
        return 0, "low"
    unique_rules = {str(item.get("ruleKey") or "") for item in findings if str(item.get("ruleKey") or "")}
    max_signal = max(_finding_signal_score(item) for item in findings)
    multi_bonus = min(18, max(0, len(findings) - 1) * 5)
    diversity_bonus = min(12, max(0, len(unique_rules) - 1) * 6)
    file_bonus = _file_exposure_bonus(file_path)
    secret_like_count = sum(1 for item in findings if bool(item.get("secretLike")))
    secret_bonus = 0
    if secret_like_count:
        secret_bonus += 10
        secret_bonus += min(8, max(0, secret_like_count - 1) * 4)
    risk_score = min(100, max_signal + multi_bonus + diversity_bonus + file_bonus + secret_bonus)
    severity = _severity_from_score(risk_score)
    return risk_score, severity


def _write_snapshot_files(
    watchlist_name: str,
    platform_key: str,
    term: str,
    repository_name: str,
    html: str,
    payload: dict[str, Any],
) -> tuple[str, str]:
    base_dir = _query_output_dir(watchlist_name, platform_key, term)
    stem = safe_stem(repository_name, "code-hit")
    html_path = base_dir / f"{stem}.html"
    artifact_path = base_dir / f"{stem}.json"
    dump_text(html_path, html)
    dump_json(artifact_path, payload)
    return str(html_path), str(artifact_path)


def _detail_payload_from_page(platform: ExposurePlatform, detail_url: str, search_url: str) -> dict[str, Any]:
    storage_state = _load_storage_state_path(platform.key)
    raw_url = _raw_file_url(platform.key, str(detail_url or ""))
    if raw_url and raw_url != detail_url:
        try:
            raw_text = _http_get_text(
                raw_url,
                headers=_search_request_headers(platform.key, storage_state),
                timeout=30,
            )
            if _normalize_text(raw_text):
                return {
                    "page_url": str(detail_url or ""),
                    "search_url": search_url,
                    "title": detail_url,
                    "html": "",
                    "screenshot_png": b"",
                    "code_text": raw_text,
                }
        except Exception:
            pass
    artifacts = fetch_page_artifacts_with_session(
        detail_url,
        storage_state_path=storage_state,
        wait_seconds=4,
        timeout_seconds=45,
    )
    html = str(artifacts.get("html") or "")
    code_text = _extract_code_text(html)
    return {
        "page_url": str(artifacts.get("url") or detail_url),
        "search_url": search_url,
        "title": _normalize_text(artifacts.get("title")) or detail_url,
        "html": html,
        "screenshot_png": artifacts.get("screenshot_png") or b"",
        "code_text": code_text,
    }


def _hydrate_detail_snapshot(platform: ExposurePlatform, detail_url: str, search_url: str) -> dict[str, Any]:
    storage_state = _load_storage_state_path(platform.key)
    artifacts = fetch_page_artifacts_with_session(
        detail_url,
        storage_state_path=storage_state,
        wait_seconds=4,
        timeout_seconds=45,
    )
    html = str(artifacts.get("html") or "")
    return {
        "page_url": str(artifacts.get("url") or detail_url),
        "search_url": search_url,
        "title": _normalize_text(artifacts.get("title")) or detail_url,
        "html": html,
        "screenshot_png": artifacts.get("screenshot_png") or b"",
        "code_text": _extract_code_text(html),
    }


def _fetch_code_search_page(platform: ExposurePlatform, search_url: str, storage_state_path: str | None) -> dict[str, Any]:
    headers = _search_request_headers(platform.key, storage_state_path)
    try:
        html = _http_get_html(search_url, headers=headers, timeout=45)
        issue = _detect_code_search_issue(platform, html, search_url, "")
        if not issue:
            return {
                "url": search_url,
                "title": "",
                "html": html,
                "screenshot_png": b"",
            }
    except Exception:
        pass
    return fetch_page_artifacts_with_session(
        search_url,
        storage_state_path=storage_state_path,
        wait_seconds=3,
        timeout_seconds=45,
    )


def _collect_search_results_across_pages(
    platform: ExposurePlatform,
    search_url: str,
    storage_state_path: str | None,
    *,
    page_limit: int,
) -> tuple[list[dict[str, Any]], str]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    issue = ""
    for page in range(1, max(1, page_limit) + 1):
        paged_url = _search_page_url(platform.key, search_url, page)
        try:
            search_page = _fetch_code_search_page(platform, paged_url, storage_state_path)
        except Exception as exc:
            issue = f"{platform.key}:page_{page}:{exc}"
            break
        page_issue = _detect_code_search_issue(
            platform,
            str(search_page.get("html") or ""),
            str(search_page.get("url") or paged_url),
            str(search_page.get("title") or ""),
        )
        if page_issue:
            issue = page_issue if page == 1 else issue
            break
        page_rows = _parse_code_search_results(
            platform,
            str(search_page.get("html") or ""),
            str(search_page.get("url") or paged_url),
        )
        if not page_rows:
            break
        new_count = 0
        for item in page_rows:
            key = f"{item.get('repositoryUrl')}|{item.get('branch')}|{item.get('filePath')}|{item.get('fileUrl')}"
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            new_count += 1
        if new_count == 0:
            break
    return results, issue


def ensure_default_code_watchlist() -> dict[str, Any]:
    with get_db_connection() as connection:
        existing = list_code_watchlists(connection)
        if existing:
            watchlist = existing[0]
            terms = list_code_watch_terms(connection, int(watchlist["id"]))
            metadata = _watchlist_metadata(watchlist)
            return {
                **watchlist,
                "terms": terms,
                "platforms": _normalize_string_list(metadata.get("platforms"), fallback=DEFAULT_CODE_PLATFORMS),
                "file_extensions": _normalize_code_file_extensions(metadata.get("file_extensions")),
                "search_page_limit": _normalize_search_page_limit(metadata.get("search_page_limit")),
                "max_results_per_term": int(metadata.get("max_results_per_term") or 5),
                "detail_fetch": bool(metadata.get("detail_fetch", True)),
                "enabled_rule_keys": _normalize_string_list(metadata.get("enabled_rule_keys"), fallback=DEFAULT_RULE_KEYS),
            }
        now = _now_utc_iso()
        watchlist_id = upsert_code_watchlist(
            connection,
            {
                "name": "默认代码监测对象",
                "organization_name": "示例企业",
                "enabled": True,
                "notes": "代码监测默认对象",
                "metadata_json": _json_dumps(
                    {
                        "platforms": DEFAULT_CODE_PLATFORMS,
                        "file_extensions": DEFAULT_FILE_EXTENSIONS,
                        "search_page_limit": DEFAULT_SEARCH_PAGE_LIMIT,
                        "max_results_per_term": 5,
                        "detail_fetch": True,
                        "enabled_rule_keys": DEFAULT_RULE_KEYS,
                    }
                ),
                "created_at": now,
                "updated_at": now,
            },
        )
        replace_code_watch_terms(
            connection,
            watchlist_id,
            [{**row, "created_at": now, "updated_at": now} for row in DEFAULT_CODE_TERMS],
        )
        connection.commit()
    return {
        "id": watchlist_id,
        "name": "默认代码监测对象",
        "organization_name": "示例企业",
        "enabled": True,
        "notes": "代码监测默认对象",
        "terms": DEFAULT_CODE_TERMS,
        "platforms": list(DEFAULT_CODE_PLATFORMS),
        "file_extensions": list(DEFAULT_FILE_EXTENSIONS),
        "search_page_limit": DEFAULT_SEARCH_PAGE_LIMIT,
        "max_results_per_term": 5,
        "detail_fetch": True,
        "enabled_rule_keys": list(DEFAULT_RULE_KEYS),
    }


def list_code_watchlists_payload() -> list[dict[str, Any]]:
    ensure_default_code_watchlist()
    with get_db_connection() as connection:
        rows = list_code_watchlists(connection)
        payloads = []
        for row in rows:
            metadata = _watchlist_metadata(row)
            payloads.append(
                {
                    **row,
                    "terms": list_code_watch_terms(connection, int(row["id"])),
                    "platforms": _normalize_string_list(metadata.get("platforms"), fallback=DEFAULT_CODE_PLATFORMS),
                    "file_extensions": _normalize_code_file_extensions(metadata.get("file_extensions")),
                    "search_page_limit": _normalize_search_page_limit(metadata.get("search_page_limit")),
                    "max_results_per_term": int(metadata.get("max_results_per_term") or 5),
                    "detail_fetch": bool(metadata.get("detail_fetch", True)),
                    "enabled_rule_keys": _normalize_string_list(metadata.get("enabled_rule_keys"), fallback=DEFAULT_RULE_KEYS),
                }
            )
        return payloads


def save_code_watchlist_payload(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_utc_iso()
    with get_db_connection() as connection:
        watchlist_id = upsert_code_watchlist(
            connection,
            {
                "id": payload.get("id"),
                "name": payload.get("name"),
                "organization_name": payload.get("organization_name"),
                "enabled": payload.get("enabled", True),
                "notes": payload.get("notes", ""),
                "metadata_json": _json_dumps(
                    {
                        "platforms": _normalize_string_list(payload.get("platforms"), fallback=DEFAULT_CODE_PLATFORMS),
                        "file_extensions": _normalize_code_file_extensions(payload.get("file_extensions")),
                        "search_page_limit": _normalize_search_page_limit(payload.get("search_page_limit")),
                        "max_results_per_term": int(payload.get("max_results_per_term") or 5),
                        "detail_fetch": bool(payload.get("detail_fetch", True)),
                        "enabled_rule_keys": _normalize_string_list(payload.get("enabled_rule_keys"), fallback=DEFAULT_RULE_KEYS),
                    }
                ),
                "created_at": payload.get("created_at") or now,
                "updated_at": now,
            },
        )
        replace_code_watch_terms(
            connection,
            watchlist_id,
            [
                {
                    "term": row.get("term"),
                    "term_type": row.get("term_type"),
                    "weight": row.get("weight", 0),
                    "enabled": row.get("enabled", True),
                    "created_at": now,
                    "updated_at": now,
                }
                for row in (payload.get("terms") or [])
            ],
        )
        connection.commit()
        watchlist = get_code_watchlist(connection, watchlist_id)
        metadata = _watchlist_metadata(watchlist or {})
        return {
            **(watchlist or {}),
            "terms": list_code_watch_terms(connection, watchlist_id),
            "platforms": _normalize_string_list(metadata.get("platforms"), fallback=DEFAULT_CODE_PLATFORMS),
            "file_extensions": _normalize_code_file_extensions(metadata.get("file_extensions")),
            "search_page_limit": _normalize_search_page_limit(metadata.get("search_page_limit")),
            "max_results_per_term": int(metadata.get("max_results_per_term") or 5),
            "detail_fetch": bool(metadata.get("detail_fetch", True)),
            "enabled_rule_keys": _normalize_string_list(metadata.get("enabled_rule_keys"), fallback=DEFAULT_RULE_KEYS),
        }


def scan_code_watchlist_once(
    watchlist_id: int,
    *,
    platforms: list[str] | None = None,
    file_extensions: list[str] | None = None,
    search_page_limit: int | None = None,
    max_results_per_term: int | None = None,
    detail_fetch: bool | None = None,
    enabled_rule_keys: list[str] | None = None,
) -> dict[str, Any]:
    ensure_default_code_watchlist()
    started_at = _now_utc_iso()
    with get_db_connection() as connection:
        watchlist = get_code_watchlist(connection, watchlist_id)
        if watchlist is None:
            raise ValueError(f"watchlist not found: {watchlist_id}")
        if not bool(watchlist.get("enabled")):
            return {"watchlist_id": watchlist_id, "scanned_terms": 0, "candidates": 0, "hits": 0, "message": "watchlist disabled"}
        terms = [item for item in list_code_watch_terms(connection, watchlist_id) if bool(item.get("enabled"))]
    metadata = _watchlist_metadata(watchlist)
    selected_platforms = _normalize_string_list(platforms or metadata.get("platforms"), fallback=DEFAULT_CODE_PLATFORMS)
    selected_extensions = _normalize_code_file_extensions(file_extensions or metadata.get("file_extensions"))
    selected_search_page_limit = _normalize_search_page_limit(search_page_limit or metadata.get("search_page_limit"))
    selected_rule_keys = _normalize_string_list(enabled_rule_keys or metadata.get("enabled_rule_keys"), fallback=DEFAULT_RULE_KEYS)
    selected_max_results = int(max_results_per_term or metadata.get("max_results_per_term") or 5)
    selected_detail_fetch = bool(detail_fetch if detail_fetch is not None else metadata.get("detail_fetch", True))

    total_candidates = 0
    total_hits = 0
    errors: list[str] = []
    seen_urls: set[str] = set()
    now = _now_utc_iso()

    for term_row in terms:
        term = _normalize_text(term_row.get("term"))
        if not term:
            continue
        for platform_key in selected_platforms:
            try:
                platform = get_exposure_platform(platform_key)
            except ValueError as exc:
                errors.append(f"{platform_key}:{term}:{exc}")
                continue
            storage_state = _load_storage_state_path(platform.key)
            if platform.key == "gitee":
                try:
                    candidates = _gitee_repo_code_search(term, selected_extensions, selected_rule_keys, page_limit=selected_search_page_limit)
                except Exception as exc:
                    errors.append(f"{platform.key}:{term}:{exc}")
                    continue
                filtered_candidates = candidates[:selected_max_results]
                total_candidates += len(filtered_candidates)
                for candidate in filtered_candidates:
                    file_url = str(candidate.get("fileUrl") or "")
                    if not file_url or file_url in seen_urls:
                        continue
                    seen_urls.add(file_url)
                    detail = {
                        "page_url": file_url,
                        "search_url": f"{GITEE_WIDGET_API_BASE}/search/widget/{GITEE_REPO_SEARCH_WIDGET}",
                        "title": candidate.get("title") or file_url,
                        "html": "",
                        "screenshot_png": b"",
                        "code_text": str(candidate.get("snippetText") or ""),
                    }
                    classification = _classify_code_hit(term, str(candidate.get("filePath") or ""), detail["code_text"], selected_rule_keys)
                    if not classification:
                        continue
                    if selected_detail_fetch and not str(detail.get("html") or "").strip():
                        try:
                            detail.update(_hydrate_detail_snapshot(platform, file_url, detail["search_url"]))
                        except Exception:
                            pass
                    classification = _classify_code_hit(term, str(candidate.get("filePath") or ""), str(detail.get("code_text") or ""), selected_rule_keys)
                    if not classification:
                        continue
                    findings = classification["findings"]
                    snippet = _extract_snippet(detail["code_text"], findings)
                    masked_snippet = _mask_snippet(snippet, findings)
                    if classification["result_layer"] == "clue":
                        snippet = _mask_preview_text(
                            _rebuild_code_preview(term, {"lineStart": 0, "lineEnd": 0}, {"candidate": candidate}, findings),
                            findings,
                        )
                        masked_snippet = snippet
                    risk_score = int(classification["risk_score"])
                    severity = str(classification["severity"])
                    language = _language_from_path(str(candidate.get("filePath") or ""))
                    raw_payload = {
                        "candidate": candidate,
                        "search_url": detail["search_url"],
                        "page_url": detail["page_url"],
                        "language": language,
                        "finding_count": len(findings),
                        "masked_fragment": masked_snippet,
                        "result_layer": classification["result_layer"],
                        "clue_markers": classification["clue_markers"],
                    }
                    with get_db_connection() as connection:
                        hit_id = upsert_code_hit(
                            connection,
                            {
                                "watchlist_id": int(watchlist["id"]),
                                "platform": platform.key,
                                "repository_name": candidate.get("repositoryName") or "",
                                "repository_owner": candidate.get("repositoryOwner") or "",
                                "repository_url": candidate.get("repositoryUrl") or "",
                                "file_path": candidate.get("filePath") or "",
                                "branch": candidate.get("branch") or "",
                                "file_url": file_url,
                                "visibility": "public",
                                "language": language,
                                "sensitive_type": classification["sensitive_type"],
                                "matched_rule": classification["matched_rule"],
                                "matched_term": term,
                                "risk_score": risk_score,
                                "severity": severity,
                                "first_seen_at": now,
                                "last_seen_at": now,
                                "raw_json": _json_dumps(raw_payload),
                            },
                        )
                        snapshot_id = insert_code_hit_snapshot(
                            connection,
                            {
                                "hit_id": hit_id,
                                "fetched_at": now,
                                "search_url": detail["search_url"],
                                "page_url": detail["page_url"],
                                "html_path": "",
                                "screenshot_path": "",
                                "code_fragment": snippet,
                                "masked_fragment": masked_snippet,
                                "raw_artifact_path": "",
                                "line_start": 0,
                                "line_end": 0,
                                "language": language,
                                "findings_json": _json_dumps(findings),
                                "raw_json": _json_dumps(raw_payload),
                            },
                        )
                        update_code_hit_last_snapshot(connection, hit_id, snapshot_id)
                        connection.commit()
                    total_hits += 1
                continue
            search_url = _search_url(platform.key, term)
            candidates, search_issue = _collect_search_results_across_pages(
                platform,
                search_url,
                storage_state,
                page_limit=selected_search_page_limit,
            )
            if search_issue:
                errors.append(f"{search_issue}:{term}")
                continue
            filtered_candidates = [item for item in candidates if _matches_extension(item.get("filePath") or "", selected_extensions)]
            if not filtered_candidates:
                expanded_candidates: list[dict[str, Any]] = []
                expanded_seen: set[str] = set()
                for query in _expanded_search_queries(term, selected_rule_keys):
                    expanded_search_url = _search_url(platform.key, query)
                    expanded_rows, expanded_issue = _collect_search_results_across_pages(
                        platform,
                        expanded_search_url,
                        storage_state,
                        page_limit=max(1, min(selected_search_page_limit, 2)),
                    )
                    if expanded_issue:
                        continue
                    for item in expanded_rows:
                        file_path = str(item.get("filePath") or "")
                        key = f"{item.get('repositoryUrl')}|{item.get('branch')}|{file_path}|{item.get('fileUrl')}"
                        if key in expanded_seen or not _matches_extension(file_path, _repo_fallback_extensions(selected_extensions)):
                            continue
                        expanded_seen.add(key)
                        expanded_candidates.append(item)
                    if len(expanded_candidates) >= max(selected_max_results * 2, 12):
                        break
                filtered_candidates = expanded_candidates
            if platform.key == "gitlab" and not filtered_candidates:
                project_candidates = [item for item in candidates if item.get("repositoryUrl")]
                for project_candidate in project_candidates[:selected_max_results]:
                    try:
                        nested_candidates = _gitlab_project_blob_search(
                            project_candidate["repositoryUrl"],
                            term,
                            storage_state,
                        )
                        filtered_candidates.extend(
                            item for item in nested_candidates
                            if _matches_extension(item.get("filePath") or "", selected_extensions)
                        )
                    except Exception as exc:
                        errors.append(f"{platform.key}:{project_candidate.get('repositoryUrl')}:nested_search:{exc}")
                deduped_nested = []
                nested_seen: set[str] = set()
                for item in filtered_candidates:
                    key = f"{item.get('repositoryUrl')}|{item.get('branch')}|{item.get('filePath')}"
                    if key in nested_seen:
                        continue
                    nested_seen.add(key)
                    deduped_nested.append(item)
                filtered_candidates = deduped_nested
            if platform.key == "gitlab" and not filtered_candidates:
                try:
                    filtered_candidates = _gitlab_repo_fallback_code_search(
                        term,
                        storage_state,
                        _repo_fallback_extensions(selected_extensions),
                        max(selected_max_results * 2, 12),
                        page_limit=max(1, min(selected_search_page_limit, 3)),
                    )
                except Exception as exc:
                    errors.append(f"{platform.key}:{term}:repo_fallback:{exc}")
            if platform.key == "github" and not filtered_candidates:
                try:
                    filtered_candidates = _github_repo_fallback_code_search(
                        term,
                        selected_extensions,
                        selected_rule_keys,
                        max(selected_max_results * 2, 12),
                        page_limit=max(1, min(selected_search_page_limit, 3)),
                    )
                except Exception as exc:
                    errors.append(f"{platform.key}:{term}:repo_fallback:{exc}")
            filtered_candidates.sort(
                key=lambda item: _candidate_priority(item, selected_rule_keys),
                reverse=True,
            )
            filtered_candidates = filtered_candidates[:selected_max_results]
            total_candidates += len(filtered_candidates)
            for candidate in filtered_candidates:
                file_url = str(candidate.get("fileUrl") or "")
                if not file_url or file_url in seen_urls:
                    continue
                seen_urls.add(file_url)
                try:
                    if platform.key == "gitlab" and candidate.get("snippetText"):
                        detail = {
                            "page_url": file_url,
                            "search_url": search_url,
                            "title": candidate.get("title") or file_url,
                            "html": "",
                            "screenshot_png": b"",
                            "code_text": str(candidate.get("snippetText") or ""),
                        }
                    elif selected_detail_fetch:
                        detail = _detail_payload_from_page(platform, file_url, search_url)
                    else:
                        detail = {
                            "page_url": file_url,
                            "search_url": search_url,
                            "title": candidate.get("title") or file_url,
                            "html": "",
                            "screenshot_png": b"",
                            "code_text": candidate.get("snippetText") or candidate.get("title") or "",
                        }
                except Exception as exc:
                    errors.append(f"{platform.key}:{file_url}:{exc}")
                    continue
                if candidate.get("snippetText") and (
                    not detail.get("code_text")
                    or str(detail.get("code_text") or "").startswith(".turbo-progress-bar")
                ):
                    detail["code_text"] = str(candidate.get("snippetText") or "")
                elif candidate.get("snippetText"):
                    snippet_text = str(candidate.get("snippetText") or "")
                    detail_findings = _collect_findings(str(detail.get("code_text") or ""), selected_rule_keys)
                    snippet_findings = _collect_findings(snippet_text, selected_rule_keys)
                    if snippet_findings and not detail_findings:
                        detail["code_text"] = snippet_text
                if not _term_matches_context(term, candidate, detail["code_text"]):
                    continue
                location = _parse_code_location(platform.key, file_url) or {}
                effective_file_path = str(candidate.get("filePath") or location.get("file_path") or "")
                classification = _classify_code_hit(term, effective_file_path, str(detail.get("code_text") or ""), selected_rule_keys)
                if not classification:
                    continue
                if selected_detail_fetch and not str(detail.get("html") or "").strip():
                    try:
                        detail.update(_hydrate_detail_snapshot(platform, file_url, search_url))
                    except Exception:
                        pass
                    classification = _classify_code_hit(term, effective_file_path, str(detail.get("code_text") or ""), selected_rule_keys)
                    if not classification:
                        continue
                findings = classification["findings"]
                snippet = _extract_snippet(detail["code_text"], findings)
                masked_snippet = _mask_snippet(snippet, findings)
                if classification["result_layer"] == "clue":
                    snippet = _rebuild_code_preview(term, {"lineStart": 0, "lineEnd": 0}, {"candidate": candidate}, findings)
                    masked_snippet = snippet
                risk_score = int(classification["risk_score"])
                severity = str(classification["severity"])
                language = _language_from_path(str(candidate.get("filePath") or location.get("file_path") or ""))
                raw_payload = {
                    "candidate": candidate,
                    "search_url": search_url,
                    "page_url": detail["page_url"],
                    "language": language,
                    "finding_count": len(findings),
                    "masked_fragment": masked_snippet,
                    "result_layer": classification["result_layer"],
                    "clue_markers": classification["clue_markers"],
                }
                with get_db_connection() as connection:
                    hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": platform.key,
                            "repository_name": candidate.get("repositoryName") or location.get("repository_name") or "",
                            "repository_owner": candidate.get("repositoryOwner") or location.get("repository_owner") or "",
                            "repository_url": candidate.get("repositoryUrl") or location.get("repository_url") or "",
                            "file_path": candidate.get("filePath") or location.get("file_path") or "",
                            "branch": candidate.get("branch") or location.get("branch") or "",
                            "file_url": file_url,
                            "visibility": "public",
                            "language": language,
                            "sensitive_type": classification["sensitive_type"],
                            "matched_rule": classification["matched_rule"],
                            "matched_term": term,
                            "risk_score": risk_score,
                            "severity": severity,
                            "first_seen_at": now,
                            "last_seen_at": now,
                            "raw_json": _json_dumps(raw_payload),
                        },
                    )
                    html_path = ""
                    artifact_path = ""
                    html_path, artifact_path = _write_snapshot_files(
                        str(watchlist["name"]),
                        platform.key,
                        term,
                        f"{candidate.get('repositoryName')}-{safe_stem(candidate.get('filePath') or '', 'file')}",
                        str(detail.get("html") or ""),
                        {
                            **raw_payload,
                            "findings": findings,
                            "code_fragment": snippet,
                            "masked_fragment": masked_snippet,
                        },
                    )
                    snapshot_id = insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": now,
                            "search_url": search_url,
                            "page_url": detail["page_url"],
                            "html_path": html_path,
                            "screenshot_path": "",
                            "code_fragment": snippet,
                            "masked_fragment": masked_snippet,
                            "raw_artifact_path": artifact_path,
                            "line_start": int(candidate.get("lineStart") or location.get("line_start") or 0),
                            "line_end": int(candidate.get("lineEnd") or location.get("line_end") or 0),
                            "language": language,
                            "findings_json": _json_dumps(findings),
                            "raw_json": _json_dumps(raw_payload),
                        },
                    )
                    update_code_hit_last_snapshot(connection, hit_id, snapshot_id)
                    connection.commit()
                total_hits += 1

    finished_at = _now_utc_iso()
    with get_db_connection() as connection:
        insert_code_scan_run(
            connection,
            {
                "watchlist_id": int(watchlist["id"]),
                "platforms_json": _json_dumps(selected_platforms),
                "requested_terms_json": _json_dumps([_normalize_text(item.get("term")) for item in terms if _normalize_text(item.get("term"))]),
                "candidate_count": total_candidates,
                "hit_count": total_hits,
                "error_count": len(errors),
                "status": "failed" if errors and total_hits == 0 else "partial" if errors else "succeeded",
                "errors_json": _json_dumps(errors),
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
        connection.commit()
    return {
        "watchlist_id": watchlist_id,
        "watchlist_name": watchlist["name"],
        "scanned_terms": len(terms),
        "candidates": total_candidates,
        "hits": total_hits,
        "errors": errors,
        "platforms": selected_platforms,
        "file_extensions": selected_extensions,
        "search_page_limit": selected_search_page_limit,
        "max_results_per_term": selected_max_results,
        "detail_fetch": selected_detail_fetch,
        "enabled_rule_keys": selected_rule_keys,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def list_code_hits_payload(
    *,
    watchlist_id: int | None = None,
    review_status: str | None = None,
    platform: str | None = None,
    sensitive_type: str | None = None,
    limit: int | None = 200,
) -> list[dict[str, Any]]:
    ensure_default_code_watchlist()
    payloads: list[dict[str, Any]] = []
    with get_db_connection() as connection:
        rows = list_code_hits(
            connection,
            watchlist_id=watchlist_id,
            review_status=review_status,
            platform=platform,
            sensitive_type=sensitive_type,
            limit=limit,
        )
        for row in rows:
            raw_payload = _parse_json(row.get("raw_json"), {})
            latest_snapshot = (list_code_hit_snapshots(connection, int(row["id"])) or [{}])[0]
            findings = _parse_json(latest_snapshot.get("findings_json"), []) if latest_snapshot else []
            result_layer = _code_result_layer(str(row.get("sensitive_type") or ""), raw_payload)
            computed_score, computed_severity = (
                _score_code_hit(str(row.get("file_path") or ""), findings)
                if result_layer == "sensitive" and findings
                else _score_clue_hit(str(row.get("matched_term") or ""), str(row.get("file_path") or ""), str((raw_payload or {}).get("code_text") or (raw_payload or {}).get("masked_fragment") or ""))[:2]
                if result_layer == "clue"
                else (int(row.get("risk_score") or 0), str(row.get("severity") or "low"))
            )
            sensitive_label = CODE_CLUE_RULE_LABEL if result_layer == "clue" else SENSITIVE_RULE_MAP.get(str(row.get("sensitive_type") or ""), SensitiveRule("", "", re.compile(""), 0)).label or row.get("sensitive_type") or ""
            payloads.append(
                {
                    "id": int(row["id"]),
                    "watchlistId": int(row["watchlist_id"]),
                    "watchlistName": row.get("watchlist_name") or "",
                    "organizationName": row.get("organization_name") or "",
                    "platform": row.get("platform") or "",
                    "platformLabel": _platform_label(str(row.get("platform") or "")),
                    "repositoryName": row.get("repository_name") or "",
                    "repositoryOwner": row.get("repository_owner") or "",
                    "repositoryFullName": "/".join(
                        part for part in [row.get("repository_owner") or "", row.get("repository_name") or ""] if part
                    ),
                    "repositoryUrl": row.get("repository_url") or "",
                    "filePath": row.get("file_path") or "",
                    "branch": row.get("branch") or "",
                    "fileUrl": row.get("file_url") or "",
                    "visibility": row.get("visibility") or "public",
                    "language": row.get("language") or "",
                    "sensitiveType": row.get("sensitive_type") or "",
                    "sensitiveLabel": sensitive_label,
                    "matchedRule": row.get("matched_rule") or "",
                    "matchedTerm": row.get("matched_term") or "",
                    "resultLayer": result_layer,
                    "resultLayerLabel": "敏感命中" if result_layer == "sensitive" else "线索命中",
                    "riskScore": computed_score,
                    "severity": computed_severity,
                    "reviewStatus": row.get("review_status") or "new",
                    "evidenceCount": int(row.get("evidence_count") or 0),
                    "firstSeenAt": row.get("first_seen_at") or "",
                    "lastSeenAt": row.get("last_seen_at") or "",
                    "lastSnapshotId": row.get("last_snapshot_id"),
                    "summary": _normalize_text((raw_payload or {}).get("masked_fragment") or "")[:220],
                    "secretLike": any(bool(item.get("secretLike")) for item in findings)
                    if findings
                    else bool(SENSITIVE_RULE_MAP.get(str(row.get("sensitive_type") or ""), SensitiveRule("", "", re.compile(""), 0)).secret_like),
                }
            )
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    payloads.sort(
        key=lambda item: (
            severity_rank.get(str(item.get("severity") or "low"), 0),
            int(item.get("riskScore") or 0),
            str(item.get("lastSeenAt") or ""),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    return payloads


def build_code_hit_detail(hit_id: int) -> dict[str, Any] | None:
    with get_db_connection() as connection:
        row = get_code_hit(connection, hit_id)
        if row is None:
            return None
        watchlist = get_code_watchlist(connection, int(row["watchlist_id"]))
        snapshots = list_code_hit_snapshots(connection, hit_id)
        reviews = list_code_hit_reviews(connection, hit_id)
    raw_payload = _parse_json(row.get("raw_json"), {})
    formatted_snapshots: list[dict[str, Any]] = []
    for item in snapshots:
        html_path = Path(str(item.get("html_path") or "")) if item.get("html_path") else None
        artifact_path = Path(str(item.get("raw_artifact_path") or "")) if item.get("raw_artifact_path") else None
        formatted_snapshots.append(
            {
                "id": int(item["id"]),
                "fetchedAt": item.get("fetched_at") or "",
                "searchUrl": item.get("search_url") or "",
                "pageUrl": item.get("page_url") or "",
                "htmlPath": str(html_path or ""),
                "htmlUrl": _public_output_url(html_path) if html_path else "",
                "screenshotPath": "",
                "screenshotUrl": "",
                "rawArtifactPath": str(artifact_path or ""),
                "rawArtifactUrl": _public_output_url(artifact_path) if artifact_path else "",
                "codeFragment": item.get("code_fragment") or "",
                "maskedFragment": item.get("masked_fragment") or "",
                "lineStart": int(item.get("line_start") or 0),
                "lineEnd": int(item.get("line_end") or 0),
                "language": item.get("language") or "",
                "findings": _parse_json(item.get("findings_json"), []),
            }
        )
    latest_snapshot = formatted_snapshots[0] if formatted_snapshots else {}
    preview_assets = []
    if latest_snapshot.get("htmlUrl"):
        preview_assets.append({"kind": "html", "label": "页面快照", "url": latest_snapshot["htmlUrl"]})
    if latest_snapshot.get("rawArtifactUrl"):
        preview_assets.append({"kind": "artifact", "label": "原始抓取", "url": latest_snapshot["rawArtifactUrl"]})
    findings = latest_snapshot.get("findings") or []
    result_layer = _code_result_layer(str(row.get("sensitive_type") or ""), raw_payload)
    code_preview = _rebuild_code_preview(
        str(row.get("matched_term") or ""),
        latest_snapshot,
        raw_payload,
        findings,
    )
    risk_score, severity = (
        _score_code_hit(str(row.get("file_path") or ""), findings)
        if result_layer == "sensitive" and findings
        else _score_clue_hit(str(row.get("matched_term") or ""), str(row.get("file_path") or ""), code_preview or str(raw_payload.get("masked_fragment") or ""))[:2]
        if result_layer == "clue"
        else (int(row.get("risk_score") or 0), str(row.get("severity") or "low"))
    )
    matched_term_contexts = _extract_matched_term_contexts(str(row.get("matched_term") or ""), row, latest_snapshot, raw_payload)
    clue_markers = list(raw_payload.get("clue_markers") or []) if isinstance(raw_payload, dict) else _collect_clue_markers(str(row.get("matched_term") or ""), code_preview)
    risk_reasons = (
        _build_code_risk_reasons(str(row.get("matched_term") or ""), str(row.get("file_path") or ""), findings)
        if result_layer == "sensitive"
        else _build_code_clue_reasons(str(row.get("matched_term") or ""), str(row.get("file_path") or ""), clue_markers)
    )
    sensitive_label = CODE_CLUE_RULE_LABEL if result_layer == "clue" else SENSITIVE_RULE_MAP.get(str(row.get("sensitive_type") or ""), SensitiveRule("", "", re.compile(""), 0)).label or row.get("sensitive_type") or ""
    return {
        "id": int(row["id"]),
        "watchlistId": int(row["watchlist_id"]),
        "watchlistName": watchlist.get("name") if watchlist else "",
        "organizationName": watchlist.get("organization_name") if watchlist else "",
        "platform": row.get("platform") or "",
        "platformLabel": _platform_label(str(row.get("platform") or "")),
        "repositoryName": row.get("repository_name") or "",
        "repositoryOwner": row.get("repository_owner") or "",
        "repositoryFullName": "/".join(
            part for part in [row.get("repository_owner") or "", row.get("repository_name") or ""] if part
        ),
        "repositoryUrl": row.get("repository_url") or "",
        "filePath": row.get("file_path") or "",
        "branch": row.get("branch") or "",
        "fileUrl": row.get("file_url") or "",
        "visibility": row.get("visibility") or "public",
        "language": row.get("language") or "",
        "sensitiveType": row.get("sensitive_type") or "",
        "sensitiveLabel": sensitive_label,
        "matchedRule": row.get("matched_rule") or "",
        "matchedTerm": row.get("matched_term") or "",
        "resultLayer": result_layer,
        "resultLayerLabel": "敏感命中" if result_layer == "sensitive" else "线索命中",
        "matchedTermContexts": matched_term_contexts,
        "riskScore": risk_score,
        "severity": severity,
        "reviewStatus": row.get("review_status") or "new",
        "evidenceCount": int(row.get("evidence_count") or 0),
        "firstSeenAt": row.get("first_seen_at") or "",
        "lastSeenAt": row.get("last_seen_at") or "",
        "rawPayload": raw_payload,
        "latestSnapshot": latest_snapshot,
        "previewAssets": preview_assets,
        "snapshots": formatted_snapshots,
        "reviews": reviews,
        "findings": findings,
        "codePreview": code_preview,
        "sourceLinks": [
            {"label": "仓库地址", "url": row.get("repository_url") or ""},
            {"label": "文件地址", "url": row.get("file_url") or ""},
            {"label": "检索页面", "url": latest_snapshot.get("searchUrl") or ""},
        ],
        "riskAnalysis": {
            "score": risk_score,
            "severity": severity,
            "reasons": risk_reasons,
        },
    }


def add_code_monitoring_review(hit_id: int, *, status: str, reviewer: str = "", note: str = "") -> dict[str, Any]:
    with get_db_connection() as connection:
        add_code_hit_review(
            connection,
            {
                "hit_id": int(hit_id),
                "status": status,
                "reviewer": reviewer,
                "note": note,
                "created_at": _now_utc_iso(),
            },
        )
        connection.commit()
    detail = build_code_hit_detail(hit_id)
    if detail is None:
        raise ValueError(f"code hit not found: {hit_id}")
    return detail


def list_code_scan_runs_payload(watchlist_id: int | None = None, limit: int | None = 50) -> list[dict[str, Any]]:
    ensure_default_code_watchlist()
    with get_db_connection() as connection:
        rows = list_code_scan_runs(connection, watchlist_id=watchlist_id, limit=limit)
    payloads: list[dict[str, Any]] = []
    for row in rows:
        payloads.append(
            {
                "id": int(row["id"]),
                "watchlistId": int(row["watchlist_id"]),
                "watchlistName": row.get("watchlist_name") or "",
                "organizationName": row.get("organization_name") or "",
                "platforms": _normalize_string_list(row.get("platforms_json"), fallback=DEFAULT_CODE_PLATFORMS),
                "requestedTerms": _parse_json(row.get("requested_terms_json"), []),
                "candidateCount": int(row.get("candidate_count") or 0),
                "hitCount": int(row.get("hit_count") or 0),
                "errorCount": int(row.get("error_count") or 0),
                "status": str(row.get("status") or "unknown"),
                "errors": _parse_json(row.get("errors_json"), []),
                "startedAt": str(row.get("started_at") or ""),
                "finishedAt": str(row.get("finished_at") or ""),
            }
        )
    return payloads


def _format_day_bucket(value: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SHANGHAI_TZ).date().isoformat()


def build_code_monitoring_summary() -> dict[str, Any]:
    rows = list_code_hits_payload(limit=500)
    now = datetime.now(SHANGHAI_TZ).date()
    trend_counter: dict[str, int] = {}
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).isoformat()
        trend_counter[day] = 0
    for row in rows:
        bucket = _format_day_bucket(row.get("lastSeenAt") or row.get("firstSeenAt"))
        if bucket in trend_counter:
            trend_counter[bucket] += 1

    platform_counts: dict[str, int] = {}
    sensitive_counts: dict[str, int] = {}
    risk_counts = {"high": 0, "medium": 0, "low": 0}
    review_counts: dict[str, int] = {}
    high_risk_repos: set[str] = set()
    secret_like_count = 0
    recent_count = 0
    clue_hit_count = 0
    sensitive_hit_count = 0
    for row in rows:
        platform_counts[row["platformLabel"]] = platform_counts.get(row["platformLabel"], 0) + 1
        sensitive_label = SENSITIVE_RULE_MAP.get(str(row.get("sensitiveType") or ""), SensitiveRule("", "", re.compile(""), 0)).label or str(row.get("sensitiveType") or "未知")
        sensitive_counts[sensitive_label] = sensitive_counts.get(sensitive_label, 0) + 1
        risk_counts[str(row.get("severity") or "low")] = risk_counts.get(str(row.get("severity") or "low"), 0) + 1
        review_key = str(row.get("reviewStatus") or "new")
        review_counts[review_key] = review_counts.get(review_key, 0) + 1
        if str(row.get("severity") or "low") == "high":
            high_risk_repos.add(str(row.get("repositoryUrl") or ""))
        if bool(row.get("secretLike")):
            secret_like_count += 1
        if str(row.get("resultLayer") or "sensitive") == "clue":
            clue_hit_count += 1
        else:
            sensitive_hit_count += 1
        if _format_day_bucket(row.get("lastSeenAt") or row.get("firstSeenAt")) == now.isoformat():
            recent_count += 1

    watchlists = list_code_watchlists_payload()
    enabled_term_count = sum(
        1
        for watchlist in watchlists
        for term in (watchlist.get("terms") or [])
        if bool(term.get("enabled"))
    )
    sessions = build_platform_session_payloads(module="code_monitoring", manageable_only=True)
    configured_sessions = [item for item in sessions if bool(item.get("configured"))]
    invalid_sessions = [item for item in sessions if str(item.get("status") or "") in {"invalid", "missing", "unavailable"}]
    latest_scan = list_code_scan_runs_payload(limit=1)
    latest_scan_row = latest_scan[0] if latest_scan else {}
    return {
        "totalHits": len(rows),
        "sensitiveSnippetCount": sensitive_hit_count,
        "clueHitCount": clue_hit_count,
        "secretLikeCount": secret_like_count,
        "highRiskRepoCount": len([item for item in high_risk_repos if item]),
        "platformCount": len(platform_counts),
        "configuredSessionCount": len(configured_sessions),
        "invalidSessionCount": len(invalid_sessions),
        "watchlistCount": len(watchlists),
        "enabledTermCount": enabled_term_count,
        "lastScanAt": str(latest_scan_row.get("finishedAt") or ""),
        "lastCandidateCount": int(latest_scan_row.get("candidateCount") or 0),
        "lastHitCount": int(latest_scan_row.get("hitCount") or 0),
        "lastErrorCount": int(latest_scan_row.get("errorCount") or 0),
        "recentCount": recent_count,
        "trend": [{"date": key, "value": value} for key, value in trend_counter.items()],
        "platformDistribution": [{"name": key, "value": value} for key, value in sorted(platform_counts.items(), key=lambda item: item[1], reverse=True)],
        "sensitiveTypeTop": [{"name": key, "value": value} for key, value in sorted(sensitive_counts.items(), key=lambda item: item[1], reverse=True)[:8]],
        "riskDistribution": [
            {"key": "high", "label": "高危", "value": risk_counts.get("high", 0)},
            {"key": "medium", "label": "中危", "value": risk_counts.get("medium", 0)},
            {"key": "low", "label": "低危", "value": risk_counts.get("low", 0)},
        ],
        "reviewDistribution": [{"key": key, "value": value} for key, value in sorted(review_counts.items(), key=lambda item: item[1], reverse=True)],
    }
