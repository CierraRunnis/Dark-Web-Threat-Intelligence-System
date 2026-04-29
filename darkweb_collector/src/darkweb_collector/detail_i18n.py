from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock, Thread
from urllib.error import HTTPError

from darkweb_collector.runtime import project_root
from darkweb_collector.vulnerability_i18n import translate_text_online


_CACHE_LOCK = Lock()
_CACHE: dict[str, str] | None = None
_CACHE_DIRTY = False
_IN_FLIGHT: set[str] = set()
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def _cache_path() -> Path:
    return project_root() / "data" / "detail_translation_cache.json"


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _looks_translatable(value: str) -> bool:
    if not value:
        return False
    english_words = re.findall(r"[A-Za-z]{3,}", value)
    return len(english_words) >= 6


def _looks_title_translatable(value: str) -> bool:
    if not value:
        return False
    english_words = re.findall(r"[A-Za-z]{3,}", value)
    return len(english_words) >= 2 or (len(value) >= 18 and len(english_words) >= 1)


def _load_cache() -> dict[str, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _cache_path()
    if not path.exists():
        _CACHE = {}
        return _CACHE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    _CACHE = {str(key): str(value) for key, value in dict(payload).items()}
    return _CACHE


def _save_cache() -> None:
    global _CACHE_DIRTY
    if not _CACHE_DIRTY:
        return
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_CACHE or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    _CACHE_DIRTY = False


def _split_for_translation(text: str, *, max_chunk_length: int = 900) -> list[str]:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chunk_length:
        return [normalized]

    sentences = [item.strip() for item in _SENTENCE_SPLIT_RE.split(normalized) if item.strip()]
    if not sentences:
        return [normalized]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chunk_length:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [normalized]


def translate_event_detail_text_with_meta(value: str | None) -> tuple[str, bool, str | None]:
    raw = _normalize_text(value)
    if not raw:
        return raw, False, None
    if not _looks_translatable(raw):
        return raw, False, "not_needed"

    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(raw)
        if cached:
            return cached, cached != raw, None

    translated_parts: list[str] = []
    try:
        for chunk in _split_for_translation(raw):
            translated_parts.append(_normalize_text(translate_text_online(chunk)))
    except HTTPError as error:
        if error.code == 429:
            return raw, False, "rate_limited"
        return raw, False, f"http_{error.code}"
    except Exception:
        return raw, False, "service_unavailable"

    translated = "\n\n".join(part for part in translated_parts if part).strip() or raw
    applied = translated != raw
    with _CACHE_LOCK:
        cache = _load_cache()
        cache[raw] = translated
        global _CACHE_DIRTY
        _CACHE_DIRTY = True
        _save_cache()
    return translated, applied, None if applied else "unchanged"


def translate_event_detail_text_live(value: str | None) -> str:
    translated, _, _ = translate_event_detail_text_with_meta(value)
    return translated


def translate_event_title_live(value: str | None, *, fallback: str | None = None) -> str:
    raw = _normalize_text(value)
    fallback_text = _normalize_text(fallback) or raw
    if not raw:
        return fallback_text

    with _CACHE_LOCK:
        cache = _load_cache()
        if raw in cache:
            return cache[raw]

    if not _looks_title_translatable(raw):
        return fallback_text

    try:
        translated = _normalize_text(translate_text_online(raw))
    except Exception:
        return fallback_text

    translated = translated or fallback_text
    with _CACHE_LOCK:
        cache = _load_cache()
        cache[raw] = translated
        global _CACHE_DIRTY
        _CACHE_DIRTY = True
        _save_cache()
    return translated


def _translate_and_cache(raw: str) -> None:
    try:
        translated = translate_event_detail_text_live(raw) or raw
        with _CACHE_LOCK:
            cache = _load_cache()
            cache[raw] = translated
            global _CACHE_DIRTY
            _CACHE_DIRTY = True
            _save_cache()
    finally:
        with _CACHE_LOCK:
            _IN_FLIGHT.discard(raw)


def translate_event_detail_text_cached(value: str | None) -> str:
    raw = _normalize_text(value)
    if not raw or not _looks_translatable(raw):
        return raw

    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(raw)
        if cached:
            return cached
        if raw not in _IN_FLIGHT:
            _IN_FLIGHT.add(raw)
            Thread(
                target=_translate_and_cache,
                args=(raw,),
                name="detail-translation-warmup",
                daemon=True,
            ).start()
    return raw
