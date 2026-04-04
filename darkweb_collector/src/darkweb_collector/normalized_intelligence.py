from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha1
import json
from pathlib import Path
import re
from typing import Any

from darkweb_collector.config import get_site_config
from darkweb_collector.db import (
    get_normalized_intelligence_cache_state,
    get_normalized_intelligence_event,
    list_normalized_intelligence_events,
    replace_normalized_intelligence_events,
    upsert_normalized_intelligence_cache_state,
)
from darkweb_collector.runtime import project_root
from darkweb_collector.utils import safe_stem


DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z0-9]+")

SOURCE_LABELS = {
    "darkforums": "DarkForums",
    "dragonforce": "DragonForce",
    "dragonforceblog": "DragonForce",
    "chaos": "Chaos",
    "lynx": "Lynx",
}

STATUS_LABELS = {
    "published": "已公开",
    "going": "协商中",
    "transferring": "传输中",
    "stopped": "已停止",
    "unknown": "未知",
}

INDUSTRY_LABELS = {
    "other": "其他",
    "unknown": "未知",
    "government": "政府",
    "finance": "金融",
    "healthcare": "医疗",
    "technology": "科技",
    "military": "军事",
    "retail": "零售",
    "education": "教育",
    "telecommunications": "通信",
    "energy": "能源",
    "transportation": "交通",
    "entertainment": "文娱",
}

REGION_LABELS = {
    "unknown": "未知",
    "north_america": "北美",
    "europe": "欧洲",
    "asia": "亚洲",
    "middle_east": "中东",
    "africa": "非洲",
    "oceania": "大洋洲",
    "south_america": "南美",
}

COUNTRY_LABELS = {
    "unknown": "未知",
    "US": "美国",
    "GB": "英国",
    "CN": "中国",
    "RU": "俄罗斯",
    "AU": "澳大利亚",
    "DE": "德国",
    "FR": "法国",
    "IT": "意大利",
    "ES": "西班牙",
    "MX": "墨西哥",
    "ZA": "南非",
    "CL": "智利",
    "CA": "加拿大",
    "RO": "罗马尼亚",
    "CH": "瑞士",
    "MY": "马来西亚",
    "EG": "埃及",
    "AR": "阿根廷",
    "BR": "巴西",
    "IN": "印度",
    "ID": "印度尼西亚",
    "PL": "波兰",
    "JP": "日本",
    "KR": "韩国",
    "SG": "新加坡",
    "AE": "阿联酋",
    "SA": "沙特阿拉伯",
}

COUNTRY_REGION_MAP = {
    "US": "北美",
    "CA": "北美",
    "MX": "北美",
    "GB": "欧洲",
    "DE": "欧洲",
    "FR": "欧洲",
    "IT": "欧洲",
    "ES": "欧洲",
    "RO": "欧洲",
    "CH": "欧洲",
    "PL": "欧洲",
    "RU": "欧洲",
    "CN": "亚洲",
    "IN": "亚洲",
    "ID": "亚洲",
    "JP": "亚洲",
    "KR": "亚洲",
    "SG": "亚洲",
    "MY": "亚洲",
    "AE": "中东",
    "SA": "中东",
    "ZA": "非洲",
    "EG": "非洲",
    "AR": "南美",
    "BR": "南美",
    "CL": "南美",
    "AU": "大洋洲",
}

COUNTRY_HINT_PATTERNS = {
    "US": [
        r"\bunited states\b",
        r"\busa\b",
        r"\bamerican\b",
        r"\bnew york\b",
        r"\bcalifornia\b",
        r"\btexas\b",
        r"\bflorida\b",
        r"\bohio\b",
        r"\bnew jersey\b",
        r"\butah\b",
        r"\bbountiful\b",
        r"\bchicago\b",
        r"\bmassachusetts\b",
    ],
    "GB": [
        r"\bunited kingdom\b",
        r"\buk\b",
        r"\bbritain\b",
        r"\bbritish\b",
        r"\bengland\b",
        r"\blondon\b",
        r"\bliverpool\b",
        r"\bmanchester\b",
    ],
    "CN": [r"\bchina\b", r"\bchinese\b", r"\bbeijing\b", r"\bshanghai\b", r"\bguangzhou\b", r"\bshenzhen\b"],
    "RU": [r"\brussia\b", r"\brussian\b", r"\bmoscow\b", r"\bst\.?\s*petersburg\b"],
    "AU": [r"\baustralia\b", r"\baustralian\b", r"\bsydney\b", r"\bmelbourne\b", r"\bqueensland\b"],
    "DE": [r"\bgermany\b", r"\bgerman\b", r"\bberlin\b", r"\bmunich\b", r"\bhamburg\b", r"\bbruchsal\b"],
    "FR": [r"\bfrance\b", r"\bfrench\b", r"\bparis\b"],
    "IT": [r"\bitaly\b", r"\bitalian\b", r"\bmilan\b", r"\bmeda\b", r"\brome\b"],
    "ES": [r"\bspain\b", r"\bspanish\b", r"\bmadrid\b", r"\bbarcelona\b"],
    "MX": [r"\bmexico\b", r"\bmexican\b", r"\bchiapas\b", r"\bmexico city\b"],
    "ZA": [r"\bsouth africa\b", r"\bsandton\b", r"\bjohannesburg\b", r"\bcape town\b"],
    "CL": [r"\bchile\b", r"\bchilean\b", r"\bsantiago\b"],
    "CA": [r"\bcanada\b", r"\bcanadian\b", r"\btoronto\b", r"\bmontreal\b", r"\bwinnipeg\b"],
    "RO": [r"\bromania\b", r"\bromanian\b", r"\bbucharest\b"],
    "CH": [r"\bswitzerland\b", r"\bswiss\b", r"\bzurich\b", r"\bgeneva\b"],
    "MY": [r"\bmalaysia\b", r"\bmalaysian\b", r"\bkuala lumpur\b"],
    "EG": [r"\begypt\b", r"\begyptian\b", r"\bcairo\b"],
    "AR": [r"\bargentina\b", r"\bargentine\b", r"\bbuenos aires\b"],
    "BR": [r"\bbrazil\b", r"\bbrazilian\b", r"\bsao paulo\b"],
    "IN": [r"\bindia\b", r"\bindian\b", r"\bnew delhi\b", r"\bmumbai\b"],
    "ID": [r"\bindonesia\b", r"\bindonesian\b", r"\bjakarta\b"],
    "PL": [r"\bpoland\b", r"\bpolish\b", r"\bwarsaw\b"],
    "JP": [r"\bjapan\b", r"\bjapanese\b", r"\btokyo\b"],
    "KR": [r"\bkorea\b", r"\bsouth korea\b", r"\bseoul\b"],
    "SG": [r"\bsingapore\b"],
    "AE": [r"\buae\b", r"\bunited arab emirates\b", r"\bdubai\b", r"\babu dhabi\b"],
    "SA": [r"\bsaudi arabia\b", r"\briyadh\b"],
}

COUNTRY_DOMAIN_SUFFIX_HINTS = {
    "co.za": "ZA",
    "com.au": "AU",
    "com.mx": "MX",
    "co.uk": "GB",
    "uk": "GB",
    "ru": "RU",
    "cn": "CN",
    "jp": "JP",
    "kr": "KR",
    "sg": "SG",
    "my": "MY",
    "de": "DE",
    "fr": "FR",
    "it": "IT",
    "es": "ES",
    "ch": "CH",
    "pl": "PL",
    "cl": "CL",
    "br": "BR",
    "ar": "AR",
    "mx": "MX",
    "au": "AU",
    "za": "ZA",
    "eg": "EG",
}

NOISY_VICTIM_DOMAINS = {
    "zoominfo.com",
    "dropmefiles.com",
    "mediafire.com",
    "pastebin.com",
    "mega.nz",
}

INDUSTRY_PRIORITY = [
    "军事",
    "金融",
    "医疗",
    "制造业",
    "科技",
    "交通",
    "通信",
    "能源",
    "政府",
    "教育",
    "文娱",
    "零售",
]

GENERIC_ENTITY_TERMS = {
    "data",
    "dataset",
    "database",
    "databases",
    "records",
    "record",
    "details",
    "detail",
    "dump",
    "leak",
    "leaked",
    "selling",
    "sale",
    "sample",
    "samples",
    "fullz",
    "credential",
    "credentials",
    "account",
    "accounts",
    "information",
    "documents",
    "document",
    "personal",
    "partial",
    "complete",
    "rows",
    "victim",
    "victims",
    "files",
    "archive",
    "package",
    "combo",
    "combolist",
    "list",
    "unknown",
}

INDUSTRY_KEYWORDS = {
    "军事": ["military", "defense", "defence", "army", "navy", "air force", "missile", "weapon", "munitions", "warfare", "national security"],
    "金融": ["bank", "banking", "finance", "financial", "fintech", "insurance", "payment", "investment", "capital management", "wealth management", "advisory", "retirement"],
    "医疗": ["health", "healthcare", "medical", "hospital", "clinic", "pharma", "medical devices", "pain management"],
    "科技": ["software", "saas", "cloud", "hosting", "tech", "technology", "digital", "electronics", "photo frame"],
    "制造业": ["manufacturing", "industrial", "factory", "equipment", "construction", "engineering", "manufacturer", "packaging", "hydraulic", "chemical", "materials", "furniture", "components", "architectural", "interior", "craftsmanship"],
    "零售": ["retail", "shop", "shopping", "ecommerce", "e-commerce", "store"],
    "教育": ["school", "college", "university", "education", "academy"],
    "政府": ["government", "gov", "ministry", "municipal", "police", "public sector"],
    "交通": ["transport", "logistics", "shipping", "airline", "airport", "rail", "freight", "trucking"],
    "能源": ["energy", "oil", "gas", "power", "electric", "utility"],
    "通信": ["telecom", "telecommunications", "mobile", "carrier", "broadband", "communications"],
    "文娱": ["media", "entertainment", "marketing", "destination marketing", "philharmonic", "orchestra", "concert", "advertising", "agency"],
}

REGION_KEYWORDS = {
    "北美": [" usa ", " us ", " united states", " north america", "canada", "mexico"],
    "欧洲": ["europe", "european", "germany", "france", "italy", "spain", "uk", "england", "poland", "netherlands"],
    "亚洲": ["asia", "asian", "china", "india", "japan", "korea", "singapore", "vietnam", "thailand", "indonesia"],
    "中东": ["middle east", "uae", "saudi", "qatar", "oman", "kuwait", "israel"],
    "南美": ["south america", "brazil", "argentina", "chile", "colombia", "peru"],
    "非洲": ["africa", "nigeria", "kenya", "south africa", "ghana", "morocco"],
    "大洋洲": ["australia", "new zealand", "oceania"],
}

RECENT_EVENT_HOURS = 72
SPIKE_WINDOW_DAYS = 7
NORMALIZATION_SCHEMA_VERSION = "2026-04-04-governance-v2"

REGION_DOMAIN_SUFFIX_HINTS = {
    "fr": "欧洲",
    "de": "欧洲",
    "es": "欧洲",
    "it": "欧洲",
    "uk": "欧洲",
    "nl": "欧洲",
    "pl": "欧洲",
    "tr": "欧洲",
    "us": "北美",
    "ca": "北美",
    "mx": "北美",
    "cn": "亚洲",
    "jp": "亚洲",
    "kr": "亚洲",
    "sg": "亚洲",
    "vn": "亚洲",
    "th": "亚洲",
    "id": "亚洲",
    "bd": "亚洲",
    "pk": "亚洲",
    "ae": "中东",
    "sa": "中东",
    "qa": "中东",
    "om": "中东",
    "kw": "中东",
    "iq": "中东",
    "ir": "中东",
    "il": "中东",
    "ma": "非洲",
    "dz": "非洲",
    "eg": "非洲",
    "ng": "非洲",
    "ke": "非洲",
    "za": "非洲",
    "br": "南美",
    "ar": "南美",
    "cl": "南美",
    "co": "南美",
    "pe": "南美",
    "au": "大洋洲",
    "nz": "大洋洲",
}

REGION_CODE_HINTS = {
    "FR": "欧洲",
    "DE": "欧洲",
    "ES": "欧洲",
    "IT": "欧洲",
    "UK": "欧洲",
    "PL": "欧洲",
    "TR": "欧洲",
    "US": "北美",
    "USA": "北美",
    "CA": "北美",
    "MX": "北美",
    "CN": "亚洲",
    "JP": "亚洲",
    "KR": "亚洲",
    "SG": "亚洲",
    "VN": "亚洲",
    "TH": "亚洲",
    "ID": "亚洲",
    "IQ": "中东",
    "IR": "中东",
    "AE": "中东",
    "SA": "中东",
    "QA": "中东",
    "OM": "中东",
    "KW": "中东",
    "MA": "非洲",
    "DZ": "非洲",
    "EG": "非洲",
    "NG": "非洲",
    "KE": "非洲",
    "BR": "南美",
    "AR": "南美",
    "CL": "南美",
    "CO": "南美",
    "PE": "南美",
    "AU": "大洋洲",
    "NZ": "大洋洲",
}

REGION_CITY_HINTS = {
    "paris": "欧洲",
    "london": "欧洲",
    "madrid": "欧洲",
    "rome": "欧洲",
    "istanbul": "欧洲",
    "casablanca": "非洲",
    "rabat": "非洲",
    "algiers": "非洲",
    "cairo": "非洲",
    "baghdad": "中东",
    "dubai": "中东",
    "doha": "中东",
    "riyadh": "中东",
    "amman": "中东",
    "tokyo": "亚洲",
    "beijing": "亚洲",
    "shanghai": "亚洲",
    "seoul": "亚洲",
    "bangkok": "亚洲",
    "jakarta": "亚洲",
    "new york": "北美",
    "los angeles": "北美",
    "toronto": "北美",
    "montreal": "北美",
    "sao paulo": "南美",
    "buenos aires": "南美",
    "santiago": "南美",
    "melbourne": "大洋洲",
    "sydney": "大洋洲",
    "auckland": "大洋洲",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for candidate in (raw, raw.replace(" UTC", "+00:00"), raw.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    for fmt in ("%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _format_dt(value: str | None) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return value or ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_date(value: str | None) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return (value or "").split(" ", 1)[0]
    return dt.astimezone().strftime("%Y-%m-%d")


def _event_hash(*parts: str) -> str:
    payload = "|".join((part or "").strip() for part in parts)
    return sha1(payload.encode("utf-8")).hexdigest()[:16]


def _normalize_whitespace(value: str | None) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _normalize_label(value: str | None) -> str:
    return _normalize_whitespace(value).strip(" ,;:()[]{}")


def _looks_like_domain(value: str | None) -> bool:
    return bool(value and DOMAIN_RE.fullmatch(value.strip().lower()))


def _normalize_domain(value: str | None) -> str:
    return _normalize_label(value).lower().removeprefix("www.")


def _canonical_key(value: str | None) -> str:
    cleaned = _normalize_label(value).lower()
    return re.sub(r"[^a-z0-9.]+", "-", cleaned).strip("-")


def _label_industry(value: str | None) -> str:
    raw = _normalize_label(value)
    lowered = raw.lower()
    return INDUSTRY_LABELS.get(lowered, raw or "未知")


def _label_region(value: str | None) -> str:
    raw = _normalize_label(value)
    lowered = raw.lower()
    return REGION_LABELS.get(lowered, raw or "未知")


def _label_source(value: str | None) -> str:
    raw = _normalize_label(value).lower()
    return SOURCE_LABELS.get(raw, _normalize_label(value) or "未知")


def _label_country(code: str | None) -> str:
    raw = _normalize_label(code).upper()
    return COUNTRY_LABELS.get(raw, "未知")


def _region_from_country_code(code: str | None) -> str:
    raw = _normalize_label(code).upper()
    return COUNTRY_REGION_MAP.get(raw, "未知")


def _display_region(country: str | None, macro_region: str | None) -> str:
    country_label = _normalize_label(country)
    region_label = _normalize_label(macro_region)
    if country_label and country_label != "未知":
        return country_label
    if region_label and region_label != "未知":
        return region_label
    return "未知"


def _is_noisy_domain(domain: str | None) -> bool:
    normalized = _normalize_domain(domain)
    return not normalized or normalized.endswith(".onion") or normalized in NOISY_VICTIM_DOMAINS


def _domain_country_code(domain: str | None) -> str:
    normalized = _normalize_domain(domain)
    if not normalized:
        return ""
    for suffix, code in sorted(COUNTRY_DOMAIN_SUFFIX_HINTS.items(), key=lambda item: len(item[0]), reverse=True):
        if normalized.endswith(f".{suffix}") or normalized == suffix:
            return code
    return ""


def _count_keyword_matches(text: str, keyword: str) -> int:
    escaped = re.escape(keyword.lower())
    pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return len(re.findall(pattern, text.lower()))


def _infer_industry_bundle(*texts: tuple[str, int]) -> dict[str, Any]:
    scores: dict[str, int] = defaultdict(int)
    sources: dict[str, list[str]] = defaultdict(list)
    for source_name, weight, text in texts:
        normalized = _normalize_whitespace(text).lower()
        if not normalized:
            continue
        for industry in INDUSTRY_PRIORITY:
            matches = 0
            for keyword in INDUSTRY_KEYWORDS.get(industry, []):
                matches += _count_keyword_matches(normalized, keyword)
            if matches:
                scores[industry] += matches * weight
                sources[industry].append(source_name)
    if not scores:
        return {"industry": "未知", "source": "unknown", "score": 0}
    industry = max(scores.items(), key=lambda item: (item[1], -INDUSTRY_PRIORITY.index(item[0])))[0]
    source = "+".join(dict.fromkeys(sources[industry])) or "text"
    return {"industry": industry, "source": source, "score": scores[industry]}


def _infer_country_bundle(*texts: tuple[str, int]) -> dict[str, Any]:
    scores: dict[str, int] = defaultdict(int)
    sources: dict[str, list[str]] = defaultdict(list)
    evidence: dict[str, list[str]] = defaultdict(list)

    for source_name, weight, text in texts:
        normalized = _normalize_whitespace(text)
        lowered = normalized.lower()
        if not lowered:
            continue

        for code, patterns in COUNTRY_HINT_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, lowered)
                if not match:
                    continue
                scores[code] += weight
                sources[code].append(source_name)
                evidence[code].append(match.group(0))
                break

        for domain in _extract_domains(normalized):
            if _is_noisy_domain(domain):
                continue
            code = _domain_country_code(domain)
            if code:
                scores[code] += max(1, weight - 3)
                sources[code].append(f"{source_name}:domain")
                evidence[code].append(domain)

    if not scores:
        return {
            "country": "未知",
            "country_code": "",
            "macro_region": "未知",
            "source": "unknown",
            "score": 0,
            "evidence": [],
        }

    country_code = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
    return {
        "country": _label_country(country_code),
        "country_code": country_code,
        "macro_region": _region_from_country_code(country_code),
        "source": "+".join(dict.fromkeys(sources[country_code])) or "text",
        "score": scores[country_code],
        "evidence": list(dict.fromkeys(evidence[country_code]))[:6],
    }


def _build_quality_scores(event: dict[str, Any], geo_bundle: dict[str, Any], industry_bundle: dict[str, Any]) -> tuple[int, int]:
    confidence = 25
    completeness = 30

    if event.get("victim") and event.get("victim") != "未知实体":
        confidence += 15
        completeness += 10
    if geo_bundle.get("country") and geo_bundle["country"] != "未知":
        confidence += min(25, int(geo_bundle.get("score") or 0))
        completeness += 20
    if industry_bundle.get("industry") and industry_bundle["industry"] != "未知":
        confidence += min(20, int(industry_bundle.get("score") or 0))
        completeness += 15
    if event.get("detail_text"):
        completeness += 10
    if event.get("disclosure_time"):
        completeness += 10
    if event.get("source_url"):
        completeness += 5

    return min(confidence, 100), min(completeness, 100)


def _propagate_entity_context(events: list[dict[str, Any]]) -> None:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        victim_key = event.get("victim_key") or "unknown"
        if victim_key == "unknown":
            continue
        grouped[victim_key].append(event)

    for victim_events in grouped.values():
        best_country_event = max(
            victim_events,
            key=lambda item: (
                item.get("country") != "未知",
                int(item.get("metadata", {}).get("country_score") or 0),
                int(item.get("confidence_score") or 0),
            ),
        )
        best_industry_event = max(
            victim_events,
            key=lambda item: (
                item.get("industry") != "未知",
                int(item.get("metadata", {}).get("industry_score") or 0),
                int(item.get("confidence_score") or 0),
            ),
        )
        for event in victim_events:
            metadata = event.setdefault("metadata", {})
            if event.get("country") in {"", "未知"} and best_country_event.get("country") not in {"", "未知"}:
                event["country"] = best_country_event["country"]
                event["country_code"] = best_country_event.get("country_code") or ""
                event["region"] = best_country_event.get("region") or event.get("region") or "未知"
                metadata["country_source"] = f"{metadata.get('country_source', 'unknown')}+victim_group"
                metadata.setdefault("tag_sources", []).append("victim_group:country")
                event["confidence_score"] = min(int(event.get("confidence_score") or 0) + 8, 100)
                event["completeness_score"] = min(int(event.get("completeness_score") or 0) + 10, 100)
            if event.get("industry") in {"", "未知"} and best_industry_event.get("industry") not in {"", "未知"}:
                event["industry"] = best_industry_event["industry"]
                metadata["industry_source"] = f"{metadata.get('industry_source', 'unknown')}+victim_group"
                metadata.setdefault("tag_sources", []).append("victim_group:industry")
                event["confidence_score"] = min(int(event.get("confidence_score") or 0) + 6, 100)
                event["completeness_score"] = min(int(event.get("completeness_score") or 0) + 8, 100)
def _coerce_resource_list(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    if isinstance(value, list):
        resources: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, dict):
                url = _normalize_label(item.get("url"))
                if url:
                    resources.append({"label": _normalize_label(item.get("label") or item.get("name") or url), "url": url})
            elif isinstance(item, str):
                url = _normalize_label(item)
                if url:
                    resources.append({"label": url, "url": url})
        return resources
    if isinstance(value, str):
        items = [_normalize_label(item) for item in value.split(",")]
        return [{"label": item, "url": item} for item in items if item]
    return []


def _site_output_dir(site_name: str) -> Path | None:
    try:
        return get_site_config(site_name).output_dir
    except Exception:
        return None


def _public_output_url(path: Path) -> str:
    output_root = project_root() / "output"
    relative_path = path.resolve().relative_to(output_root.resolve())
    return f"/collector-output/{relative_path.as_posix()}"


def _resource_entry(path: Path, label: str) -> dict[str, str]:
    return {"label": label, "url": _public_output_url(path)}


def _forum_output_resources(row_dict: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    output_dir = _site_output_dir(str(row_dict.get("site_name") or ""))
    topic_url = _normalize_label(row_dict.get("topic_url"))
    if output_dir is None or not topic_url:
        return [], []
    section = _normalize_label(row_dict.get("section")) or "section"
    detail_dir = output_dir / section / "details"
    artifact_stem = _event_hash(topic_url)[:10]
    html_path = detail_dir / f"{artifact_stem}.html"
    json_path = detail_dir / f"{artifact_stem}.json"
    png_path = detail_dir / f"{artifact_stem}.png"
    resources: list[dict[str, str]] = []
    screenshots: list[dict[str, str]] = []
    if html_path.exists():
        resources.append(_resource_entry(html_path, "本地HTML镜像"))
    if json_path.exists():
        resources.append(_resource_entry(json_path, "本地JSON镜像"))
    if png_path.exists():
        screenshots.append(_resource_entry(png_path, "详情截图"))
    return resources, screenshots


def _victim_output_resources(row_dict: dict[str, Any], raw_json: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    site_name = str(row_dict.get("site_name") or "")
    output_dir = _site_output_dir(site_name)
    if output_dir is None:
        return [], []
    content_hash = str(raw_json.get("content_hash") or row_dict.get("content_hash") or "")
    domain = str(raw_json.get("domain") or row_dict.get("domain") or "")
    name = str(raw_json.get("name") or row_dict.get("name") or "")
    if site_name == "lynx":
        artifact_stem = safe_stem(f"{content_hash[:10]}_{name[:30]}")
    else:
        artifact_stem = safe_stem(f"{content_hash[:10]}_{domain or name}")
    detail_dir = output_dir / "details"
    html_path = detail_dir / f"{artifact_stem}.html"
    json_path = detail_dir / f"{artifact_stem}.json"
    png_path = detail_dir / f"{artifact_stem}.png"
    resources: list[dict[str, str]] = []
    screenshots: list[dict[str, str]] = []
    if html_path.exists():
        resources.append(_resource_entry(html_path, "本地HTML镜像"))
    if json_path.exists():
        resources.append(_resource_entry(json_path, "本地JSON镜像"))
    if png_path.exists():
        screenshots.append(_resource_entry(png_path, "详情截图"))
    return resources, screenshots


def _extract_domains(*texts: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for text in texts:
        for match in DOMAIN_RE.findall(text or ""):
            domain = _normalize_domain(match)
            if domain and domain not in seen:
                seen.add(domain)
                results.append(domain)
    return results


def _clean_entity_candidates(candidates: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = _normalize_label(candidate)
        lowered = label.lower()
        if not label or lowered in seen:
            continue
        words = {word.lower() for word in WORD_RE.findall(label)}
        if words and words.issubset(GENERIC_ENTITY_TERMS):
            continue
        if not _looks_like_domain(label) and any(term in lowered for term in ("sell ", "selling", "sample", "data", "records")) and len(words) <= 5:
            continue
        seen.add(lowered)
        cleaned.append(label)
    return cleaned


def _pick_primary_victim(candidates: list[str], title: str, content: str, fallback_domains: list[str]) -> tuple[str, str]:
    scored: list[tuple[int, str]] = []
    title_lower = title.lower()
    content_lower = content.lower()
    for candidate in _clean_entity_candidates(candidates):
        lowered = candidate.lower()
        score = 0
        if _looks_like_domain(candidate):
            score += 8
        if lowered and lowered in title_lower:
            score += 5
        if lowered and lowered in content_lower:
            score += 2
        if len(candidate.split()) <= 5:
            score += 1
        scored.append((score, candidate))
    if scored:
        scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        victim = scored[0][1]
        victim_key = _normalize_domain(victim) if _looks_like_domain(victim) else _canonical_key(victim)
        return victim, victim_key
    for domain in fallback_domains:
        if _is_noisy_domain(domain):
            continue
        return domain, domain
    return "未知实体", "unknown"


def _infer_industry(*texts: str) -> str:
    bundle = _infer_industry_bundle(*[(f"text_{index}", 4 if index == 0 else 3, text) for index, text in enumerate(texts)])
    return bundle["industry"]


def _infer_region(*texts: str) -> str:
    country_bundle = _infer_country_bundle(*[(f"text_{index}", 6 if index == 0 else 4, text) for index, text in enumerate(texts)])
    if country_bundle["country"] != "未知":
        return country_bundle["macro_region"]

    merged = f" {' '.join(texts).lower()} "
    scores: dict[str, int] = {}

    for domain in _extract_domains(*texts):
        suffix = domain.rsplit(".", 1)[-1]
        region = REGION_DOMAIN_SUFFIX_HINTS.get(suffix)
        if region:
            scores[region] = scores.get(region, 0) + 5

    for code, region in REGION_CODE_HINTS.items():
        code_lower = code.lower()
        if f"[{code_lower}]" in merged or f" {code_lower} " in merged:
            scores[region] = scores.get(region, 0) + 4

    for city, region in REGION_CITY_HINTS.items():
        if city in merged:
            scores[region] = scores.get(region, 0) + 3

    for label, keywords in REGION_KEYWORDS.items():
        if any(keyword in merged for keyword in keywords):
            scores[label] = scores.get(label, 0) + 2

    if scores:
        best_region, best_score = max(scores.items(), key=lambda item: (item[1], item[0]))
        if best_score >= 2:
            return best_region
    return "未知"


def _classify_forum_leak_type(section: str, title: str, content: str) -> str:
    text = f"{title} {content}".lower()
    if any(keyword in text for keyword in ("password", "credential", "combo", "combolist", "fullz", "account")):
        return "凭证泄露"
    if any(keyword in text for keyword in ("source code", "repo", "repository", "git", "github")):
        return "源代码泄露"
    if any(keyword in text for keyword in ("passport", "license", "statement", "document", "id card", "selfie")):
        return "证件文档"
    if any(keyword in text for keyword in ("database", "dump", "records", "sql", "breach", "leak")):
        return "数据库泄露"
    if section == "sellers_place":
        return "交易售卖"
    return "数据泄露"


def _severity_from_forum(section: str, leak_type: str) -> str:
    if leak_type in {"凭证泄露", "源代码泄露"}:
        return "critical"
    if section == "databases" or leak_type in {"数据库泄露", "证件文档"}:
        return "high"
    if section == "sellers_place":
        return "medium"
    return "medium"


def _severity_from_status(status: str) -> str:
    lowered = status.lower()
    if lowered == "published":
        return "critical"
    if lowered in {"going", "transferring"}:
        return "high"
    if lowered == "stopped":
        return "medium"
    return "medium"


def _recent_cutoff(hours: int = RECENT_EVENT_HOURS) -> datetime:
    return _now_utc() - timedelta(hours=hours)


def _source_signature_payload(connection) -> dict[str, Any]:
    forum_stats = connection.execute(
        """
        SELECT COUNT(*) AS count, MAX(id) AS max_id, MAX(fetched_at) AS latest_at
        FROM forum_details
        """
    ).fetchone()
    victim_stats = connection.execute(
        """
        SELECT COUNT(*) AS count, MAX(id) AS max_id, MAX(COALESCE(published_at_utc, '')) AS latest_at
        FROM victims
        """
    ).fetchone()
    victim_detail_stats = connection.execute(
        """
        SELECT COUNT(*) AS count, MAX(id) AS max_id, MAX(fetched_at_utc) AS latest_at
        FROM victim_details
        """
    ).fetchone()
    return {
        "forum_details": dict(forum_stats),
        "victims": dict(victim_stats),
        "victim_details": dict(victim_detail_stats),
    }


def _build_source_signature(connection) -> str:
    payload = {
        "version": NORMALIZATION_SCHEMA_VERSION,
        **_source_signature_payload(connection),
    }
    return sha1(_json_dumps(payload).encode("utf-8")).hexdigest()


def _normalized_event_count(connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM normalized_intelligence_events").fetchone()
    return int(row["count"]) if row else 0


def should_refresh_normalized_intelligence(connection) -> bool:
    cache_state = get_normalized_intelligence_cache_state(connection)
    current_signature = _build_source_signature(connection)
    current_event_count = _normalized_event_count(connection)
    if cache_state is None:
        return True
    if cache_state.get("source_signature") != current_signature:
        return True
    if int(cache_state.get("event_count") or 0) != current_event_count:
        return True
    return False


def _forum_rows(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT d.id, d.site_name, d.section, d.topic_url, d.content, d.attachments,
               d.victims, d.attackers, d.fetched_at, d.raw_json,
               COALESCE(t.title, d.topic_url) AS title,
               GROUP_CONCAT(fv.victim_name, '||') AS victim_names,
               GROUP_CONCAT(COALESCE(fv.industry, ''), '||') AS industries,
               GROUP_CONCAT(COALESCE(fv.region, ''), '||') AS regions
        FROM forum_details d
        LEFT JOIN forum_topics t
          ON t.site_name = d.site_name
         AND t.section = d.section
         AND t.url = d.topic_url
        LEFT JOIN forum_victims fv
          ON fv.forum_detail_id = d.id
        GROUP BY d.id
        ORDER BY d.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _victim_rows(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT v.id, v.site_name, v.source_url, v.detail_url, v.name, v.display_label, v.domain,
               v.status, v.published_at_utc, v.claimed_size, v.claimed_size_gb, v.content_hash,
               v.raw_json, vd.text_excerpt, vd.page_title, vd.fetched_at_utc, vd.raw_json AS detail_raw_json
        FROM victims v
        LEFT JOIN victim_details vd
          ON vd.id = (
              SELECT vd2.id
              FROM victim_details vd2
              WHERE vd2.victim_id = v.id
              ORDER BY datetime(vd2.fetched_at_utc) DESC, vd2.id DESC
              LIMIT 1
          )
        ORDER BY v.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _build_forum_base_event(row: dict[str, Any]) -> dict[str, Any]:
    title = _normalize_label(row.get("title")) or _normalize_label(row.get("topic_url")) or "未命名论坛帖子"
    content = _normalize_whitespace(row.get("content"))
    raw_json = _parse_json(row.get("raw_json"))
    topic_url = _normalize_label(row.get("topic_url"))
    victim_names = [item for item in str(row.get("victim_names") or "").split("||") if _normalize_label(item)]
    victim_candidates = victim_names[:]
    victims_field = _normalize_label(row.get("victims"))
    if victims_field:
        victim_candidates.extend(part for part in victims_field.split(",") if _normalize_label(part))
    domain_candidates = _extract_domains(title, content, victims_field)
    victim, victim_key = _pick_primary_victim(victim_candidates, title, content, domain_candidates)
    attacker_candidates = [_normalize_label(item) for item in str(row.get("attackers") or "").split(",") if _normalize_label(item)]
    attacker = attacker_candidates[0] if attacker_candidates else _label_source(row.get("site_name"))
    industry_candidates = [
        _label_industry(item)
        for item in str(row.get("industries") or "").split("||")
        if _normalize_label(item) and _label_industry(item) not in {"未知", "其他"}
    ]
    region_candidates = [
        _label_region(item)
        for item in str(row.get("regions") or "").split("||")
        if _normalize_label(item) and _label_region(item) != "未知"
    ]
    industry_bundle = _infer_industry_bundle(
        ("title", 7, title),
        ("content", 5, content),
        ("victim", 4, victim),
        ("domains", 3, " ".join(domain_candidates)),
    )
    industry = industry_candidates[0] if industry_candidates else industry_bundle["industry"]
    geo_bundle = _infer_country_bundle(
        ("title", 9, title),
        ("content", 6, content),
        ("victim", 5, victim),
        ("url", 4, topic_url),
        ("domains", 4, " ".join(domain_candidates)),
    )
    region = region_candidates[0] if region_candidates else geo_bundle["macro_region"]
    leak_type = _classify_forum_leak_type(str(row.get("section") or ""), title, content)
    severity = _severity_from_forum(str(row.get("section") or ""), leak_type)
    mirror_resources = _coerce_resource_list(row.get("attachments"))
    local_resources, screenshot_resources = _forum_output_resources(row)
    mirror_resources.extend(local_resources)
    if topic_url:
        mirror_resources.append({"label": "原始披露链接", "url": topic_url})
    event = {
        "event_id": f"forum:{row['site_name']}:{row['section']}:{_event_hash(topic_url)}",
        "source_kind": "forum",
        "raw_source_type": "forum_details",
        "source_site_name": str(row.get("site_name") or ""),
        "source_record_id": int(row["id"]),
        "event_type": "data_leak",
        "category": leak_type,
        "leak_type": leak_type,
        "title": title,
        "attacker": attacker,
        "victim": victim,
        "victim_key": victim_key,
        "industry": industry,
        "country": geo_bundle["country"],
        "country_code": geo_bundle["country_code"],
        "region": region,
        "disclosure_time": row.get("fetched_at") or "",
        "severity": severity,
        "source_url": topic_url,
        "detail_text": content,
        "mirror_resources": mirror_resources,
        "screenshot_resources": screenshot_resources,
        "json_preview_url": next((item["url"] for item in mirror_resources if item["url"].endswith(".json")), ""),
    }
    confidence_score, completeness_score = _build_quality_scores(event, geo_bundle, industry_bundle)
    return {
        **event,
        "confidence_score": confidence_score,
        "completeness_score": completeness_score,
        "metadata": {
            "section": str(row.get("section") or ""),
            "source": str(row.get("site_name") or ""),
            "source_label": _label_source(row.get("site_name")),
            "victim_candidates": _clean_entity_candidates(victim_candidates)[:8],
            "domain_candidates": domain_candidates[:8],
            "published_label": _format_date(row.get("fetched_at")),
            "resource_count": len(mirror_resources),
            "country_source": geo_bundle["source"],
            "country_score": geo_bundle["score"],
            "country_evidence": geo_bundle["evidence"],
            "industry_source": industry_bundle["source"],
            "industry_score": industry_bundle["score"],
            "tag_sources": [geo_bundle["source"], industry_bundle["source"]],
            "entity_link_evidence": {
                "match_method": "domain_or_title",
                "matched_fields": [name for name, value in {"title": title, "content": content, "victim": victim}.items() if value],
                "domain_candidates": domain_candidates[:5],
            },
            "risk_reasons": [],
            "raw_json": raw_json,
        },
    }


def _pick_victim_from_row(row: dict[str, Any], raw_json: dict[str, Any]) -> tuple[str, str]:
    name = _normalize_label(row.get("name")) or _normalize_label(raw_json.get("name"))
    display_label = _normalize_label(row.get("display_label"))
    domain_candidates = _extract_domains(
        name,
        display_label,
        str(row.get("domain") or ""),
        str(raw_json.get("website_url") or ""),
        str(raw_json.get("location") or ""),
    )
    if name and name.lower() != "unknown":
        victim_key = _normalize_domain(name) if _looks_like_domain(name) else _canonical_key(name)
        return name, victim_key
    for domain in domain_candidates:
        if not _is_noisy_domain(domain):
            return domain, domain
    return "未知实体", "unknown"


def _build_victim_base_event(row: dict[str, Any]) -> dict[str, Any]:
    raw_json = _parse_json(row.get("raw_json"))
    detail_raw_json = _parse_json(row.get("detail_raw_json"))
    victim, victim_key = _pick_victim_from_row(row, raw_json)
    attacker = _label_source(row.get("site_name"))
    status = _normalize_label(row.get("status") or raw_json.get("status") or "unknown").lower()
    category = STATUS_LABELS.get(status, _normalize_label(row.get("status")) or "未知")
    detail_text = _normalize_whitespace(row.get("text_excerpt") or detail_raw_json.get("text_excerpt") or raw_json.get("description"))
    website_url = _normalize_label(raw_json.get("website_url"))
    location = _normalize_label(raw_json.get("location"))
    detail_url = _normalize_label(row.get("detail_url") or raw_json.get("detail_url"))
    domain = _normalize_label(row.get("domain"))
    title = _normalize_label(row.get("display_label")) or victim
    industry_bundle = _infer_industry_bundle(
        ("title", 7, title),
        ("description", 6, _normalize_label(raw_json.get("description"))),
        ("website", 4, website_url),
        ("detail", 5, detail_text),
        ("victim", 4, victim),
    )
    industry = industry_bundle["industry"]
    geo_bundle = _infer_country_bundle(
        ("title", 8, title),
        ("description", 6, _normalize_label(raw_json.get("description"))),
        ("location", 7, location),
        ("website", 5, website_url),
        ("detail_url", 4, detail_url),
        ("domain", 5, domain),
        ("detail", 5, detail_text),
        ("victim", 4, victim),
    )
    region = geo_bundle["macro_region"]
    severity = _severity_from_status(status)
    local_resources, local_screenshots = _victim_output_resources(row, raw_json)
    mirror_resources = _coerce_resource_list(detail_url)
    mirror_resources.extend(local_resources)
    screenshot_resources = _coerce_resource_list(raw_json.get("thumbnails"))
    screenshot_resources.extend(local_screenshots)
    disclosure_time = row.get("published_at_utc") or row.get("fetched_at_utc") or ""
    if isinstance(disclosure_time, str) and disclosure_time.strip().upper() in {"PUBLISHED", "GOING", "TRANSFERING", "TRANSFERRING", "STOPPED"}:
        disclosure_time = row.get("fetched_at_utc") or ""
    event = {
        "event_id": f"victim:{row['site_name']}:{_event_hash(str(detail_url or victim))}",
        "source_kind": "victim",
        "raw_source_type": "victims",
        "source_site_name": str(row.get("site_name") or ""),
        "source_record_id": int(row["id"]),
        "event_type": "ransomware",
        "category": category,
        "leak_type": "勒索披露",
        "title": title,
        "attacker": attacker,
        "victim": victim,
        "victim_key": victim_key,
        "industry": industry,
        "country": geo_bundle["country"],
        "country_code": geo_bundle["country_code"],
        "region": region,
        "disclosure_time": disclosure_time,
        "severity": severity,
        "source_url": detail_url or _normalize_label(row.get("source_url")),
        "detail_text": detail_text,
        "mirror_resources": mirror_resources,
        "screenshot_resources": screenshot_resources,
        "json_preview_url": next((item["url"] for item in mirror_resources if item["url"].endswith(".json")), ""),
    }
    confidence_score, completeness_score = _build_quality_scores(event, geo_bundle, industry_bundle)
    return {
        **event,
        "confidence_score": confidence_score,
        "completeness_score": completeness_score,
        "metadata": {
            "status": status,
            "claimed_size": _normalize_label(row.get("claimed_size")),
            "claimed_size_gb": row.get("claimed_size_gb"),
            "source": str(row.get("site_name") or ""),
            "source_label": _label_source(row.get("site_name")),
            "published_label": _format_date(disclosure_time),
            "resource_count": len(mirror_resources),
            "country_source": geo_bundle["source"],
            "country_score": geo_bundle["score"],
            "country_evidence": geo_bundle["evidence"],
            "industry_source": industry_bundle["source"],
            "industry_score": industry_bundle["score"],
            "tag_sources": [geo_bundle["source"], industry_bundle["source"]],
            "entity_link_evidence": {
                "match_method": "display_label_or_domain",
                "matched_fields": [name for name, value in {"display_label": row.get("display_label"), "domain": domain, "detail": detail_text}.items() if value],
                "domain_candidates": [item for item in [domain, _normalize_domain(victim)] if item],
            },
            "risk_reasons": [],
            "raw_json": raw_json,
        },
    }


def _compute_spike_counters(events: list[dict[str, Any]], field: str) -> tuple[Counter[str], Counter[str]]:
    recent_cutoff = _now_utc() - timedelta(days=SPIKE_WINDOW_DAYS)
    previous_cutoff = _now_utc() - timedelta(days=SPIKE_WINDOW_DAYS * 2)
    recent_counter: Counter[str] = Counter()
    previous_counter: Counter[str] = Counter()
    for event in events:
        label = _normalize_label(event.get(field))
        if not label or label == "未知":
            continue
        event_dt = _parse_dt(str(event.get("disclosure_time") or ""))
        if event_dt is None:
            continue
        if event_dt >= recent_cutoff:
            recent_counter[label] += 1
        elif event_dt >= previous_cutoff:
            previous_counter[label] += 1
    return recent_counter, previous_counter


def _score_events(events: list[dict[str, Any]]) -> None:
    actor_counter = Counter(event["attacker"] for event in events if event["attacker"] and event["attacker"] != "未知")
    victim_counter = Counter(event["victim_key"] for event in events if event["victim_key"] and event["victim_key"] != "unknown")
    actor_sites: defaultdict[str, set[str]] = defaultdict(set)
    for event in events:
        actor_sites[event["attacker"]].add(event["source_site_name"])

    industry_recent, industry_previous = _compute_spike_counters(events, "industry")
    region_recent, region_previous = _compute_spike_counters(events, "region")
    recent_cutoff = _recent_cutoff()
    severity_points = {"critical": 30, "high": 20, "medium": 12, "low": 6}

    for event in events:
        score = severity_points.get(event["severity"], 8)
        reasons: list[str] = []
        if event["severity"] == "critical":
            reasons.append("存在高危披露事件")
        elif event["severity"] == "high":
            reasons.append("属于高风险事件类型")

        if event["leak_type"] in {"凭证泄露", "源代码泄露", "数据库泄露", "勒索披露"}:
            score += 10
            reasons.append(f"命中重点情报类型：{event['leak_type']}")

        actor = event["attacker"]
        actor_count = actor_counter.get(actor, 0)
        if actor_count >= 2:
            score += min(18, actor_count * 4)
            reasons.append("同一主体近期重复出现")

        if len(actor_sites.get(actor, set())) >= 2:
            score += 12
            reasons.append("同一主体跨站点出现")

        victim_count = victim_counter.get(event["victim_key"], 0)
        if victim_count >= 2:
            score += min(15, victim_count * 4)
            reasons.append("同一受害实体重复暴露")

        industry = event["industry"]
        if industry != "未知" and industry_recent.get(industry, 0) >= max(2, industry_previous.get(industry, 0) + 1):
            score += 8
            reasons.append("受影响行业近期活跃度上升")

        region = event["region"]
        if region != "未知" and region_recent.get(region, 0) >= max(2, region_previous.get(region, 0) + 1):
            score += 6
            reasons.append("受影响地区近期活跃度上升")

        event_dt = _parse_dt(str(event.get("disclosure_time") or ""))
        if event_dt is not None and event_dt >= recent_cutoff:
            score += 6
            reasons.append("事件在近 72 小时内发生")

        event["risk_score"] = min(score, 100)
        event["metadata"]["risk_reasons"] = reasons[:4]


def _hydrate_event_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _parse_json(row.get("event_metadata_json"))
    return {
        **row,
        "mirror_resources": _coerce_resource_list(_parse_json(row.get("mirror_resources_json"))),
        "screenshot_resources": _coerce_resource_list(_parse_json(row.get("screenshot_resources_json"))),
        "risk_reasons": [item for item in _parse_json(row.get("risk_reasons_json")) if isinstance(item, str)],
        "metadata": metadata,
        "source": metadata.get("source") or _label_source(row.get("source_site_name")),
        "country": metadata.get("country") or "未知",
        "country_code": metadata.get("country_code") or "",
        "region": metadata.get("macro_region") or row.get("region") or "未知",
        "confidence_score": int(metadata.get("confidence_score") or 0),
        "completeness_score": int(metadata.get("completeness_score") or 0),
        "country_source": metadata.get("country_source") or "unknown",
        "industry_source": metadata.get("industry_source") or "unknown",
        "tag_sources": [item for item in metadata.get("tag_sources", []) if isinstance(item, str)],
        "entity_link_evidence": metadata.get("entity_link_evidence") or {},
    }


def refresh_normalized_intelligence(connection) -> list[dict[str, Any]]:
    source_signature = _build_source_signature(connection)
    base_events: list[dict[str, Any]] = []
    for row in _forum_rows(connection):
        base_events.append(_build_forum_base_event(row))
    for row in _victim_rows(connection):
        base_events.append(_build_victim_base_event(row))

    _propagate_entity_context(base_events)
    _score_events(base_events)
    deduped_events: dict[str, dict[str, Any]] = {}
    for event in base_events:
        existing = deduped_events.get(event["event_id"])
        if existing is None:
            deduped_events[event["event_id"]] = event
            continue
        current_dt = _parse_dt(str(event.get("disclosure_time") or ""))
        existing_dt = _parse_dt(str(existing.get("disclosure_time") or ""))
        should_replace = False
        if current_dt and existing_dt:
            should_replace = current_dt >= existing_dt
        elif current_dt and not existing_dt:
            should_replace = True
        elif len(event.get("detail_text") or "") > len(existing.get("detail_text") or ""):
            should_replace = True
        if should_replace:
            merged = {**existing, **event}
            merged["mirror_resources"] = existing.get("mirror_resources", []) + [
                item for item in event.get("mirror_resources", []) if item not in existing.get("mirror_resources", [])
            ]
            merged["screenshot_resources"] = existing.get("screenshot_resources", []) + [
                item for item in event.get("screenshot_resources", []) if item not in existing.get("screenshot_resources", [])
            ]
            deduped_events[event["event_id"]] = merged
        else:
            existing["mirror_resources"] = existing.get("mirror_resources", []) + [
                item for item in event.get("mirror_resources", []) if item not in existing.get("mirror_resources", [])
            ]
            existing["screenshot_resources"] = existing.get("screenshot_resources", []) + [
                item for item in event.get("screenshot_resources", []) if item not in existing.get("screenshot_resources", [])
            ]

    updated_at = _now_utc().isoformat()
    persisted_rows: list[dict[str, Any]] = []
    for event in deduped_events.values():
        metadata_payload = {
            **event["metadata"],
            "country": event.get("country") or "未知",
            "country_code": event.get("country_code") or "",
            "macro_region": event.get("region") or "未知",
            "confidence_score": int(event.get("confidence_score") or 0),
            "completeness_score": int(event.get("completeness_score") or 0),
        }
        persisted_rows.append(
            {
                "event_id": event["event_id"],
                "source_kind": event["source_kind"],
                "raw_source_type": event["raw_source_type"],
                "source_site_name": event["source_site_name"],
                "source_record_id": event["source_record_id"],
                "event_type": event["event_type"],
                "category": event["category"],
                "leak_type": event["leak_type"],
                "title": event["title"],
                "attacker": event["attacker"],
                "victim": event["victim"],
                "victim_key": event["victim_key"],
                "industry": event["industry"],
                "region": event["region"],
                "disclosure_time": event.get("disclosure_time") or "",
                "severity": event["severity"],
                "risk_score": int(event["risk_score"]),
                "source_url": event.get("source_url") or "",
                "detail_text": event.get("detail_text") or "",
                "mirror_resources_json": _json_dumps(event.get("mirror_resources") or []),
                "screenshot_resources_json": _json_dumps(event.get("screenshot_resources") or []),
                "json_preview_url": event.get("json_preview_url") or "",
                "risk_reasons_json": _json_dumps(event["metadata"].get("risk_reasons") or []),
                "event_metadata_json": _json_dumps(metadata_payload),
                "updated_at": updated_at,
            }
        )
    replace_normalized_intelligence_events(connection, persisted_rows)
    upsert_normalized_intelligence_cache_state(
        connection,
        source_signature=source_signature,
        event_count=len(persisted_rows),
        refreshed_at=updated_at,
    )
    connection.commit()
    return load_normalized_events(connection, refresh=False)


def ensure_normalized_intelligence(connection, force: bool = False) -> list[dict[str, Any]]:
    if force or should_refresh_normalized_intelligence(connection):
        return refresh_normalized_intelligence(connection)
    return load_normalized_events(connection, refresh=False)


def load_normalized_events(connection, refresh: bool = False) -> list[dict[str, Any]]:
    if refresh:
        return ensure_normalized_intelligence(connection, force=True)
    rows = list_normalized_intelligence_events(connection)
    if rows:
        return [_hydrate_event_row(row) for row in rows]
    if get_normalized_intelligence_cache_state(connection) is None:
        return ensure_normalized_intelligence(connection, force=True)
    return []


def load_normalized_event_detail(connection, event_id: str, refresh: bool = False) -> dict[str, Any] | None:
    if refresh:
        ensure_normalized_intelligence(connection, force=True)
    row = get_normalized_intelligence_event(connection, event_id)
    if row is None and get_normalized_intelligence_cache_state(connection) is None:
        ensure_normalized_intelligence(connection, force=True)
        row = get_normalized_intelligence_event(connection, event_id)
    if row is None:
        return None
    return _hydrate_event_row(row)


def normalized_event_to_list_item(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["event_id"],
        "event_type": event["source_kind"],
        "raw_source_type": event["raw_source_type"],
        "disclosureTime": _format_date(event.get("disclosure_time")),
        "disclosureTimeRaw": event.get("disclosure_time") or "",
        "title": event["title"],
        "category": event["category"],
        "attacker": event["attacker"],
        "industry": event["industry"],
        "country": event.get("country") or "未知",
        "countryCode": event.get("country_code") or "",
        "macroRegion": event.get("region") or "未知",
        "region": _display_region(event.get("country"), event.get("region")),
        "severity": event["severity"],
        "victim": event["victim"],
        "riskScore": event["risk_score"],
        "riskReasons": event["risk_reasons"],
        "confidenceScore": int(event.get("confidence_score") or 0),
        "completenessScore": int(event.get("completeness_score") or 0),
    }


def normalized_event_to_detail(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["event_id"],
        "event_type": event["source_kind"],
        "raw_source_type": event["raw_source_type"],
        "title": event["title"],
        "disclosure_time": _format_date(event.get("disclosure_time")),
        "disclosure_time_raw": event.get("disclosure_time") or "",
        "attacker": event["attacker"],
        "disclosure_url": event.get("source_url") or "",
        "detail_text": event.get("detail_text") or "",
        "category": event["category"],
        "source": event["source"],
        "industry": event["industry"],
        "country": event.get("country") or "未知",
        "country_code": event.get("country_code") or "",
        "macro_region": event.get("region") or "未知",
        "region": _display_region(event.get("country"), event.get("region")),
        "mirror_resources": event["mirror_resources"],
        "screenshot_resources": event["screenshot_resources"],
        "json_preview_url": event.get("json_preview_url") or "",
        "victim": event["victim"],
        "risk_score": event["risk_score"],
        "risk_reasons": event["risk_reasons"],
        "leak_type": event["leak_type"],
        "severity": event["severity"],
        "confidence_score": int(event.get("confidence_score") or 0),
        "completeness_score": int(event.get("completeness_score") or 0),
        "country_source": event.get("country_source") or "unknown",
        "industry_source": event.get("industry_source") or "unknown",
        "tag_sources": event.get("tag_sources") or [],
        "entity_link_evidence": event.get("entity_link_evidence") or {},
    }


def _build_actor_ranking(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        actor = event["attacker"] or "未知"
        grouped[actor].append(event)

    ranking: list[dict[str, Any]] = []
    for actor, actor_events in grouped.items():
        actor_events.sort(
            key=lambda item: (_parse_dt(item.get("disclosure_time")) or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        sites = {item["source_site_name"] for item in actor_events if item["source_site_name"]}
        leak_type_counts = Counter(item["leak_type"] for item in actor_events if item["leak_type"])
        reasons: list[str] = []
        if len(actor_events) >= 3:
            reasons.append("近期多次出现")
        if len(sites) >= 2:
            reasons.append("跨站点出现")
        if any(item["severity"] == "critical" for item in actor_events):
            reasons.append("存在高危事件")
        ranking.append(
            {
                "actor": actor,
                "eventCount": len(actor_events),
                "crossSiteCount": len(sites),
                "averageRiskScore": round(sum(item["risk_score"] for item in actor_events) / len(actor_events)),
                "topLeakType": leak_type_counts.most_common(1)[0][0] if leak_type_counts else "未知",
                "lastSeenAt": _format_dt(actor_events[0].get("disclosure_time")),
                "reasons": reasons or ["持续活跃"],
            }
        )
    ranking.sort(key=lambda item: (item["averageRiskScore"], item["eventCount"], item["crossSiteCount"]), reverse=True)
    return ranking[:10]


def _build_victim_ranking(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        victim_key = event["victim_key"]
        if not victim_key or victim_key == "unknown":
            continue
        grouped[victim_key].append(event)

    ranking: list[dict[str, Any]] = []
    for _, victim_events in grouped.items():
        victim_events.sort(
            key=lambda item: (_parse_dt(item.get("disclosure_time")) or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        ranking.append(
            {
                "victim": victim_events[0]["victim"],
                "eventCount": len(victim_events),
                "averageRiskScore": round(sum(item["risk_score"] for item in victim_events) / len(victim_events)),
                "lastSeenAt": _format_dt(victim_events[0].get("disclosure_time")),
                "industries": sorted({item["industry"] for item in victim_events if item["industry"] and item["industry"] != "未知"})[:3],
            }
        )
    ranking.sort(key=lambda item: (item["averageRiskScore"], item["eventCount"]), reverse=True)
    return ranking[:10]


def _aggregate_dimension(events: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        key = _normalize_label(event.get(field))
        if not key or key == "未知":
            continue
        grouped[key].append(event)
    rows: list[dict[str, Any]] = []
    for key, grouped_events in grouped.items():
        rows.append(
            {
                "name": key,
                "value": len(grouped_events),
                "averageRiskScore": round(sum(item["risk_score"] for item in grouped_events) / len(grouped_events)),
            }
        )
    rows.sort(key=lambda item: (item["averageRiskScore"], item["value"]), reverse=True)
    return rows[:8]


def _build_behavior_signals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actor_ranking = _build_actor_ranking(events)
    repeated_victims = [item for item in _build_victim_ranking(events) if item["eventCount"] >= 2]
    industry_focus = _aggregate_dimension(events, "industry")
    region_focus = _aggregate_dimension(events, "region")
    signals: list[dict[str, Any]] = []
    if actor_ranking:
        top_actor = actor_ranking[0]
        signals.append(
            {
                "title": f"{top_actor['actor']} 活跃度最高",
                "description": f"共出现 {top_actor['eventCount']} 次，平均风险分 {top_actor['averageRiskScore']}。",
                "tone": "danger" if top_actor["averageRiskScore"] >= 60 else "warning",
            }
        )
    if repeated_victims:
        top_victim = repeated_victims[0]
        signals.append(
            {
                "title": f"{top_victim['victim']} 重复暴露",
                "description": f"同一受害实体出现 {top_victim['eventCount']} 次，建议优先人工复核。",
                "tone": "warning",
            }
        )
    if industry_focus:
        signals.append(
            {
                "title": f"{industry_focus[0]['name']} 为高频受影响行业",
                "description": f"当前记录 {industry_focus[0]['value']} 条，平均风险分 {industry_focus[0]['averageRiskScore']}。",
                "tone": "primary",
            }
        )
    if region_focus:
        signals.append(
            {
                "title": f"{region_focus[0]['name']} 区域持续活跃",
                "description": f"当前记录 {region_focus[0]['value']} 条，适合放入答辩中的重点区域样例。",
                "tone": "success",
            }
        )
    return signals[:4]


def build_behavior_payload(connection, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized_events = events if events is not None else load_normalized_events(connection)
    data_leak_events = [item for item in normalized_events if item["event_type"] == "data_leak"]
    ransomware_events = [item for item in normalized_events if item["event_type"] == "ransomware"]
    actor_ranking = _build_actor_ranking(normalized_events)
    victim_ranking = _build_victim_ranking(normalized_events)
    industry_focus = _aggregate_dimension(normalized_events, "industry")
    region_focus = _aggregate_dimension(normalized_events, "region")
    anomaly_events = sorted(
        normalized_events,
        key=lambda item: (item["risk_score"], _parse_dt(item.get("disclosure_time")) or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )[:12]

    return {
        "summaryCards": [
            {"label": "标准化事件", "value": str(len(normalized_events)), "description": "已完成清洗和结构化提取的情报事件数。", "tone": "primary"},
            {"label": "高风险事件", "value": str(sum(1 for item in normalized_events if item["risk_score"] >= 60)), "description": "规则评分达到 60 分及以上的事件数量。", "tone": "danger"},
            {"label": "活跃主体", "value": str(len(actor_ranking)), "description": "可用于行为分析排序的主体数量。", "tone": "warning"},
            {"label": "重复受害实体", "value": str(sum(1 for item in victim_ranking if item["eventCount"] >= 2)), "description": "多次出现的受害者实体数量。", "tone": "success"},
        ],
        "actorRiskRanking": actor_ranking,
        "victimRiskRanking": victim_ranking,
        "industryRiskDistribution": industry_focus,
        "regionRiskDistribution": region_focus,
        "anomalyEvents": [
            {
                "id": item["event_id"],
                "title": item["title"],
                "attacker": item["attacker"],
                "victim": item["victim"],
                "category": item["category"],
                "sourceSite": _label_source(item["source_site_name"]),
                "disclosureTime": _format_dt(item.get("disclosure_time")),
                "riskScore": item["risk_score"],
                "reasons": item["risk_reasons"],
            }
            for item in anomaly_events
        ],
        "behaviorSignals": _build_behavior_signals(normalized_events),
        "extractionStats": {
            "dataLeakCount": len(data_leak_events),
            "ransomwareCount": len(ransomware_events),
            "updatedAt": _format_dt(_now_utc().isoformat()),
        },
    }
