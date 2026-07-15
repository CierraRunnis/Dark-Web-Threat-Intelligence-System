from __future__ import annotations

from .base import (
    CollectRequest,
    CollectResult,
    CoverageStatus,
    JSONTransport,
    SocialAdapter,
    SocialAdapterError,
    SocialPost,
    UrllibJSONTransport,
)
from .facebook import FacebookAdapter
from .registry import get_social_adapter, register_adapter, registered_platforms
from .telegram import TelegramAdapter
from .x import XAdapter
from .youtube import YouTubeAdapter


register_adapter("x", XAdapter)
register_adapter("facebook", FacebookAdapter)
register_adapter("youtube", YouTubeAdapter)
register_adapter("telegram", TelegramAdapter)


__all__ = [
    "CollectRequest",
    "CollectResult",
    "CoverageStatus",
    "FacebookAdapter",
    "JSONTransport",
    "SocialAdapter",
    "SocialAdapterError",
    "SocialPost",
    "TelegramAdapter",
    "UrllibJSONTransport",
    "XAdapter",
    "YouTubeAdapter",
    "get_social_adapter",
    "register_adapter",
    "registered_platforms",
]
