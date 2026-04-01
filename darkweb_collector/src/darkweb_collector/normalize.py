from __future__ import annotations

from hashlib import sha256
import re


SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP])\s*$", re.IGNORECASE)


def normalize_status(value: str) -> str:
    value = (value or "").strip().lower()
    if value in {"link-going", "timer-going", "going"}:
        return "going"
    if value in {"link-published", "timer-published", "published"}:
        return "published"
    if value in {"link-transfering", "timer-transfering", "transfering", "transferring"}:
        return "transferring"
    if value in {"link-stopped", "timer-stopped", "stopped"}:
        return "stopped"
    return value or "unknown"


def size_to_gb(value: str) -> float | None:
    match = SIZE_RE.match(value or "")
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    factors = {
        "K": 1 / (1024 * 1024),
        "M": 1 / 1024,
        "G": 1.0,
        "T": 1024.0,
        "P": 1024.0 * 1024.0,
    }
    return round(number * factors[unit], 3)


def content_hash(*parts: str) -> str:
    payload = "\n".join((part or "").strip() for part in parts)
    return sha256(payload.encode("utf-8")).hexdigest()
