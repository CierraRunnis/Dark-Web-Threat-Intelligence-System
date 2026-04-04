from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from darkweb_collector.db import get_db_connection, replace_vulnerability_records
from darkweb_collector.runtime import project_root
from darkweb_collector.vulnerability_i18n import humanize_product_token
from darkweb_collector.vulnerability_i18n import translate_vulnerability_summary_live
from darkweb_collector.vulnerability_i18n import translate_vulnerability_title_live


DEFAULT_SAMPLE_FEED = project_root() / "samples" / "public_vulnerability_feed.json"
DEFAULT_LIVE_LIMIT = 20
KEV_FEED_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
HTTP_HEADERS = {
    "User-Agent": "bishe-threat-intel/1.0",
    "Accept": "application/json",
}
URL_RE = re.compile(r"https?://[^\s;]+", re.IGNORECASE)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_json(url: str, *, timeout: int = 20) -> dict[str, Any]:
    request = Request(url, headers=HTTP_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _coerce_reference_urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _coerce_versions(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def _unique_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    disclosure_time = str(record.get("disclosure_time") or record.get("published_at") or _now_utc_iso()).strip()
    reference_urls = _unique_strings(_coerce_reference_urls(record.get("reference_urls")))
    advisory_url = str(record.get("advisory_url") or (reference_urls[0] if reference_urls else "")).strip()
    return {
        "source_name": str(record.get("source_name") or "public_feed").strip(),
        "source_type": str(record.get("source_type") or "public").strip(),
        "cve_id": str(record.get("cve_id") or "").strip().upper(),
        "title": str(record.get("title") or "").strip(),
        "vendor": str(record.get("vendor") or "").strip(),
        "product": str(record.get("product") or "").strip(),
        "vulnerability_type": str(record.get("vulnerability_type") or "公开源漏洞").strip(),
        "severity": str(record.get("severity") or "high").strip().lower(),
        "cvss": record.get("cvss"),
        "is_exploited": bool(record.get("is_exploited")),
        "has_poc": bool(record.get("has_poc")),
        "patch_available": bool(record.get("patch_available")),
        "wide_impact": bool(record.get("wide_impact")),
        "disclosure_time": disclosure_time,
        "affected_versions": _coerce_versions(record.get("affected_versions")),
        "summary": str(record.get("summary") or "").strip(),
        "advisory_url": advisory_url,
        "reference_urls": reference_urls,
        "last_seen_at": str(record.get("last_seen_at") or disclosure_time).strip(),
    }


def _load_sample_feed(sample_file: str | Path | None = None) -> list[dict[str, Any]]:
    feed_path = Path(sample_file).expanduser().resolve() if sample_file else DEFAULT_SAMPLE_FEED.resolve()
    payload = json.loads(feed_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        records = payload.get("records") or []
    else:
        records = payload
    return [_normalize_record(record) for record in records if isinstance(record, dict)]


def _extract_urls(text: str) -> list[str]:
    return _unique_strings(URL_RE.findall(text or ""))


def _pick_cvss(metrics: dict[str, Any]) -> float | None:
    candidates: list[float] = []
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for item in metrics.get(key) or []:
            cvss_data = item.get("cvssData") or {}
            score = cvss_data.get("baseScore")
            try:
                if score is not None:
                    candidates.append(float(score))
            except (TypeError, ValueError):
                continue
    return max(candidates) if candidates else None


def _pick_description(cve: dict[str, Any]) -> str:
    for item in cve.get("descriptions") or []:
        if item.get("lang") == "en" and item.get("value"):
            return str(item["value"]).strip()
    for item in cve.get("descriptions") or []:
        if item.get("value"):
            return str(item["value"]).strip()
    return ""


def _format_cpe_range(match: dict[str, Any]) -> str:
    parts: list[str] = []
    criteria = str(match.get("criteria") or "")
    criteria_parts = criteria.split(":")
    product_token = criteria_parts[4] if len(criteria_parts) >= 5 else ""
    if len(criteria_parts) >= 6:
        version = criteria_parts[5]
        if version and version != "*":
            parts.append(version)
    if match.get("versionStartIncluding"):
        parts.append(f">= {match['versionStartIncluding']}")
    if match.get("versionStartExcluding"):
        parts.append(f"> {match['versionStartExcluding']}")
    if match.get("versionEndIncluding"):
        parts.append(f"<= {match['versionEndIncluding']}")
    if match.get("versionEndExcluding"):
        parts.append(f"< {match['versionEndExcluding']}")
    range_text = " ".join(parts).strip() or criteria
    product_label = humanize_product_token(product_token)
    if product_label and range_text != criteria:
        return f"{product_label}: {range_text}"
    return range_text


def _walk_configuration_nodes(node: dict[str, Any], versions: list[str]) -> None:
    for match in node.get("cpeMatch") or []:
        if not match.get("vulnerable", True):
            continue
        versions.append(_format_cpe_range(match))
    for child in node.get("children") or []:
        _walk_configuration_nodes(child, versions)


def _extract_affected_versions(cve: dict[str, Any]) -> list[str]:
    versions: list[str] = []
    for config in cve.get("configurations") or []:
        for node in config.get("nodes") or []:
            _walk_configuration_nodes(node, versions)
    return _unique_strings(versions)[:8]


def _extract_fixed_version_ranges(summary: str) -> list[str]:
    if not summary:
        return []
    match = re.search(r"fixed in (.+?)(?:\.|$)", summary, flags=re.IGNORECASE)
    if not match:
        return []
    segment = match.group(1).replace(" and ", ", ")
    ranges: list[str] = []
    for part in [item.strip() for item in segment.split(",") if item.strip()]:
        version_match = re.match(r"(.+?)\s+([0-9][0-9A-Za-z._-]*)$", part)
        if not version_match:
            continue
        product_name = humanize_product_token(version_match.group(1))
        fixed_version = version_match.group(2)
        ranges.append(f"{product_name}: < {fixed_version}")
    return _unique_strings(ranges)


def _enrich_from_nvd(cve_id: str) -> dict[str, Any]:
    query = urlencode({"cveId": cve_id})
    payload = _fetch_json(f"{NVD_API_URL}?{query}")
    vulnerabilities = payload.get("vulnerabilities") or []
    if not vulnerabilities:
        return {}
    cve = vulnerabilities[0].get("cve") or {}
    description = _pick_description(cve)
    affected_versions = _extract_affected_versions(cve)
    affected_versions = _unique_strings(affected_versions + _extract_fixed_version_ranges(description))
    return {
        "summary": description,
        "cvss": _pick_cvss(cve.get("metrics") or {}),
        "affected_versions": affected_versions,
        "nvd_url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
    }


def _derive_vulnerability_type(name: str, cwes: list[str]) -> str:
    lowered = (name or "").lower()
    for keyword, label in (
        ("remote code execution", "远程代码执行"),
        ("command injection", "命令注入"),
        ("sql injection", "SQL 注入"),
        ("use-after-free", "释放后重用"),
        ("authentication bypass", "身份认证绕过"),
        ("privilege escalation", "权限提升"),
        ("deserialization", "反序列化漏洞"),
        ("cross-site scripting", "跨站脚本"),
        ("path traversal", "路径遍历"),
        ("request smuggling", "请求走私"),
        ("memory corruption", "内存破坏"),
    ):
        if keyword in lowered:
            return label
    if cwes:
        return cwes[0]
    return "公开源漏洞"


def _build_record_from_kev(item: dict[str, Any], *, nvd_enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    cve_id = str(item.get("cveID") or "").strip().upper()
    notes = str(item.get("notes") or "")
    note_urls = _extract_urls(notes)
    nvd_url = (nvd_enrichment or {}).get("nvd_url") or (f"https://nvd.nist.gov/vuln/detail/{cve_id}" if cve_id else "")
    reference_urls = _unique_strings(note_urls + ([nvd_url] if nvd_url else []))
    required_action = str(item.get("requiredAction") or "").strip()
    summary = str((nvd_enrichment or {}).get("summary") or item.get("shortDescription") or "").strip()
    title = str(item.get("vulnerabilityName") or f"{item.get('vendorProject', '')} {item.get('product', '')}").strip()
    has_poc = any(token in f"{notes} {summary}".lower() for token in ("poc", "proof-of-concept", "proof of concept", "exploit code"))
    affected_versions = (nvd_enrichment or {}).get("affected_versions") or []
    return _normalize_record(
        {
            "source_name": "cisa_kev",
            "source_type": "official",
            "cve_id": cve_id,
            "title": translate_vulnerability_title_live(
                title,
                vendor=str(item.get("vendorProject") or "").strip(),
                product=str(item.get("product") or "").strip(),
            ),
            "vendor": str(item.get("vendorProject") or "").strip(),
            "product": str(item.get("product") or "").strip(),
            "vulnerability_type": _derive_vulnerability_type(
                str(item.get("vulnerabilityName") or ""),
                [str(cwe).strip() for cwe in item.get("cwes") or [] if str(cwe).strip()],
            ),
            "severity": "critical",
            "cvss": (nvd_enrichment or {}).get("cvss"),
            "is_exploited": True,
            "has_poc": has_poc,
            "patch_available": bool(required_action),
            "wide_impact": len(affected_versions) >= 3 or "multiple" in summary.lower() or "multiple" in notes.lower(),
            "disclosure_time": str(item.get("dateAdded") or _now_utc_iso()).strip(),
            "affected_versions": affected_versions,
            "summary": translate_vulnerability_summary_live(summary),
            "advisory_url": next((url for url in reference_urls if "nvd.nist.gov" not in url), "") or (reference_urls[0] if reference_urls else ""),
            "reference_urls": reference_urls,
            "last_seen_at": _now_utc_iso(),
        }
    )


def fetch_live_public_vulnerability_feed(*, limit: int = DEFAULT_LIVE_LIMIT) -> list[dict[str, Any]]:
    kev_payload = _fetch_json(KEV_FEED_URL)
    vulnerabilities = kev_payload.get("vulnerabilities") or []
    latest_items = sorted(
        vulnerabilities,
        key=lambda item: str(item.get("dateAdded") or ""),
        reverse=True,
    )[: max(1, int(limit))]

    records: list[dict[str, Any]] = []
    for item in latest_items:
        cve_id = str(item.get("cveID") or "").strip().upper()
        if not cve_id:
            continue
        try:
            nvd_enrichment = _enrich_from_nvd(cve_id)
        except Exception:
            nvd_enrichment = {}
        records.append(_build_record_from_kev(item, nvd_enrichment=nvd_enrichment))
    return records


def load_public_vulnerability_feed(
    sample_file: str | Path | None = None,
    *,
    limit: int = DEFAULT_LIVE_LIMIT,
    prefer_live: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    if sample_file:
        path = Path(sample_file).expanduser().resolve()
        return _load_sample_feed(path), str(path)

    if prefer_live:
        try:
            records = fetch_live_public_vulnerability_feed(limit=limit)
            if records:
                return records, KEV_FEED_URL
        except Exception:
            pass

    return _load_sample_feed(DEFAULT_SAMPLE_FEED), str(DEFAULT_SAMPLE_FEED.resolve())


def sync_public_vulnerability_feed(
    sample_file: str | Path | None = None,
    *,
    limit: int = DEFAULT_LIVE_LIMIT,
    prefer_live: bool = True,
) -> dict[str, Any]:
    records, source = load_public_vulnerability_feed(
        sample_file=sample_file,
        limit=limit,
        prefer_live=prefer_live,
    )
    with get_db_connection() as connection:
        replace_vulnerability_records(connection, records)
        connection.commit()
    return {
        "ingested": len(records),
        "source": source,
        "mode": "sample" if sample_file or not source.startswith("http") else "live",
    }
