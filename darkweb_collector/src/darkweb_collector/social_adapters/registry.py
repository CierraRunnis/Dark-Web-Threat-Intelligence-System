from __future__ import annotations

from collections.abc import Callable

from .base import SocialAdapter


_FACTORIES: dict[str, Callable[[], SocialAdapter]] = {}


def register_adapter(platform: str, factory: Callable[[], SocialAdapter]) -> None:
    normalized = platform.strip().lower()
    if not normalized:
        raise ValueError("platform is required")
    _FACTORIES[normalized] = factory


def get_social_adapter(platform: str) -> SocialAdapter:
    normalized = platform.strip().lower()
    try:
        factory = _FACTORIES[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported social platform '{platform}'") from exc
    return factory()


def registered_platforms() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))
