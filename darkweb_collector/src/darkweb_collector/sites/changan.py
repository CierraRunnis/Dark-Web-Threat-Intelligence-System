from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from typing import Any
from urllib.parse import quote_plus

from darkweb_collector.normalize import content_hash


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def _timestamp(value: Any) -> str:
    raw = _text(value)
    if raw.isdigit() and len(raw) in {10, 13}:
        seconds = int(raw) / (1000 if len(raw) == 13 else 1)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return raw


def _clean_html(value: Any) -> str:
    raw = str(value or "")
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return _text(raw)


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _named_value(value: Any) -> str:
    if isinstance(value, dict):
        return _text(_first(value, "name", "title", "label", "username", "hid", "id"))
    return _text(value)


def _image_urls(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value] if value else []
    result: list[str] = []
    for item in items:
        candidate = _first(item, "pic", "url", "src") if isinstance(item, dict) else item
        normalized = _text(candidate)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def changan_detail_url(base_url: str, goods_id: str) -> str:
    return f"{base_url.rstrip('/')}/#/detail?gid={quote_plus(goods_id)}"


def parse_changan_list(
    payload: dict[str, Any],
    *,
    base_url: str,
    collected_at_utc: str,
    max_topics: int,
    excluded_categories: Any = (),
) -> dict[str, Any]:
    excluded_values = [excluded_categories] if isinstance(excluded_categories, str) else excluded_categories
    if not isinstance(excluded_values, (list, tuple, set)):
        excluded_values = ()
    excluded = {_text(value).casefold() for value in excluded_values if _text(value)}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    goods = data.get("goods") or data.get("list") or []
    if not isinstance(goods, list):
        goods = []
    topics: list[dict[str, Any]] = []
    for item in goods[: max(max_topics, 0)]:
        if not isinstance(item, dict):
            continue
        goods_id = _text(_first(item, "id", "gid", "goods_id"))
        title = _text(_first(item, "name", "title"))
        if not goods_id or not title:
            continue
        intro = _clean_html(_first(item, "intro", "summary", "description"))
        author = _named_value(_first(item, "owner", "publisher", "seller", "user"))
        category = _named_value(_first(item, "category", "category_name", "cid"))
        if category.casefold() in excluded:
            continue
        published_at = _timestamp(_first(item, "ctime", "created_at", "created", "publish_time"))
        views = _text(_first(item, "read_count", "read", "views"))
        price = _text(_first(item, "price", "amount"))
        detail_url = changan_detail_url(base_url, goods_id)
        topics.append(
            {
                "goods_id": goods_id,
                "title": title,
                "intro": intro,
                "author": author,
                "category": category,
                "published_at": published_at,
                "views": views,
                "price": price,
                "full_url": detail_url,
                "content_hash": content_hash(
                    goods_id,
                    title,
                    intro,
                    author,
                    category,
                    published_at,
                    _clean_html(_first(item, "detail", "content", "ctt", "body")),
                    _named_value(_first(item, "originName", "origin", "source")),
                ),
                "raw": item,
            }
        )
    source_total = int(data["total"]) if data.get("total") not in (None, "") else None
    return {
        "site_name": "changan",
        "source_url": f"{base_url.rstrip('/')}/#/products",
        "section": "sellers_place",
        "collected_at_utc": collected_at_utc,
        "topic_count": len(topics),
        "total": source_total if source_total is not None else len(goods),
        "source_total": source_total,
        "source_count": len(goods),
        "topics": topics,
    }


def parse_changan_detail(
    payload: dict[str, Any],
    *,
    detail_url: str,
    collected_at_utc: str,
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    title = _text(_first(data, "name", "title"))
    intro = _clean_html(_first(data, "intro", "summary", "description"))
    body = _clean_html(_first(data, "detail", "content", "ctt", "body"))
    seller = _named_value(_first(data, "owner", "publisher", "seller", "user"))
    category = _named_value(_first(data, "category", "category_name", "cid"))
    origin = _named_value(_first(data, "originName", "origin", "source"))
    published_at = _timestamp(_first(data, "ctime", "created_at", "created", "publish_time"))
    price = _text(_first(data, "price", "amount"))
    images = _image_urls(_first(data, "pics", "images", "attachments"))

    sections = [
        title,
        intro,
        body,
        f"商品分类: {category}" if category else "",
        f"数据来源: {origin}" if origin else "",
        f"发布者: {seller}" if seller else "",
        f"价格: {price}" if price else "",
    ]
    content = "\n".join(item for item in sections if item).strip()
    return {
        "title": title or detail_url,
        "content": content,
        "author": seller,
        "timestamp": published_at,
        "published_at_utc": published_at,
        "category": category,
        "origin": origin,
        "price": price,
        "attachments": images,
        "victims": [],
        "attackers": [seller] if seller else [],
        "content_hash": content_hash(
            detail_url,
            title,
            intro,
            body,
            category,
            origin,
            seller,
            published_at,
            "\n".join(images),
        ),
        "collected_at_utc": collected_at_utc,
        "raw": data,
    }
