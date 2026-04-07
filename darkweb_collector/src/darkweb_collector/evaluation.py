from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from darkweb_collector.db import get_db_connection
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence


@dataclass(slots=True)
class GoldSample:
    source_site: str
    title: str
    expected_country: str = ""
    expected_region: str = ""
    expected_industry: str = ""


def _normalize_key(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def load_gold_samples(path: str | Path) -> list[GoldSample]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples: list[GoldSample] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        samples.append(
            GoldSample(
                source_site=str(item.get("source_site") or "").strip(),
                title=str(item.get("title") or "").strip(),
                expected_country=str(item.get("expected_country") or "").strip(),
                expected_region=str(item.get("expected_region") or "").strip(),
                expected_industry=str(item.get("expected_industry") or "").strip(),
            )
        )
    return samples


def evaluate_against_gold(samples: list[GoldSample], refresh: bool = False) -> dict[str, Any]:
    with get_db_connection() as connection:
        events = ensure_normalized_intelligence(connection, force=refresh)

    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        key = (_normalize_key(event.get("source_site_name") or ""), _normalize_key(event.get("title") or ""))
        existing = indexed.get(key)
        if existing is None:
            indexed[key] = event
            continue
        current_score = (
            int(event.get("confidence_score") or 0),
            int(event.get("completeness_score") or 0),
            int(event.get("risk_score") or 0),
        )
        existing_score = (
            int(existing.get("confidence_score") or 0),
            int(existing.get("completeness_score") or 0),
            int(existing.get("risk_score") or 0),
        )
        if current_score >= existing_score:
            indexed[key] = event

    sample_total = len(samples)
    country_total = sum(1 for item in samples if item.expected_country)
    region_total = sum(1 for item in samples if item.expected_region)
    industry_total = sum(1 for item in samples if item.expected_industry)
    country_hits = 0
    region_hits = 0
    industry_hits = 0
    missing: list[dict[str, str]] = []
    mismatches: list[dict[str, str]] = []
    per_source: dict[str, dict[str, int]] = {}

    for sample in samples:
        per_source.setdefault(sample.source_site, {"total": 0, "country_hits": 0, "region_hits": 0, "industry_hits": 0})
        per_source[sample.source_site]["total"] += 1

        event = indexed.get((_normalize_key(sample.source_site), _normalize_key(sample.title)))
        if event is None:
            missing.append({"source_site": sample.source_site, "title": sample.title})
            continue

        actual_country = str(event.get("country") or "").strip()
        actual_region = str(event.get("region") or "").strip()
        actual_industry = str(event.get("industry") or "").strip()

        if sample.expected_country and actual_country == sample.expected_country:
            country_hits += 1
            per_source[sample.source_site]["country_hits"] += 1
        elif sample.expected_country:
            mismatches.append(
                {
                    "source_site": sample.source_site,
                    "title": sample.title,
                    "field": "country",
                    "expected": sample.expected_country,
                    "actual": actual_country,
                }
            )

        if sample.expected_region and actual_region == sample.expected_region:
            region_hits += 1
            per_source[sample.source_site]["region_hits"] += 1
        elif sample.expected_region:
            mismatches.append(
                {
                    "source_site": sample.source_site,
                    "title": sample.title,
                    "field": "region",
                    "expected": sample.expected_region,
                    "actual": actual_region,
                }
            )

        if sample.expected_industry and actual_industry == sample.expected_industry:
            industry_hits += 1
            per_source[sample.source_site]["industry_hits"] += 1
        elif sample.expected_industry:
            mismatches.append(
                {
                    "source_site": sample.source_site,
                    "title": sample.title,
                    "field": "industry",
                    "expected": sample.expected_industry,
                    "actual": actual_industry,
                }
            )

    return {
        "total": sample_total,
        "country_total": country_total,
        "region_total": region_total,
        "industry_total": industry_total,
        "country_accuracy": round(country_hits / (country_total or 1) * 100, 2),
        "region_accuracy": round(region_hits / (region_total or 1) * 100, 2),
        "industry_accuracy": round(industry_hits / (industry_total or 1) * 100, 2),
        "missing": missing,
        "mismatches": mismatches,
        "per_source": per_source,
    }
