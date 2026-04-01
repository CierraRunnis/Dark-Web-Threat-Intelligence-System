from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8", errors="replace")


def safe_stem(value: str | None, fallback: str = "item") -> str:
    cleaned = SAFE_STEM_RE.sub("_", (value or "").strip()).strip("._")
    return cleaned or fallback
