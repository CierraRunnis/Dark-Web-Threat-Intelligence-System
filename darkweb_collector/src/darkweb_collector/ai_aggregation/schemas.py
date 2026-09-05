from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cron import CronValidationError, validate_five_field_cron


PROMPT_TEMPLATE = "搜索 {{keywords}} {{time_range}} 的威胁情报"
DEFAULT_SOURCES = ["darkweb", "telegram", "web"]
ALLOWED_TEMPLATE_VARIABLES = {"keywords", "time_range"}
_TEMPLATE_VARIABLE_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def normalize_keyword(value: str) -> str:
    value = " ".join(value.strip().split())
    if not value:
        raise ValueError("keyword must not be blank")
    if any(ord(char) < 32 for char in value):
        raise ValueError("keyword must not contain control characters")
    if len(value) > 128:
        raise ValueError("keyword must contain at most 128 characters")
    return value


def normalize_keywords(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        keyword = normalize_keyword(str(value or ""))
        key = keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(keyword)
    if not normalized:
        raise ValueError("at least one keyword is required")
    if len(normalized) > 30:
        raise ValueError("at most 30 keywords are allowed")
    return normalized


def validate_prompt_template(value: str) -> str:
    template = str(value or "").strip()
    if not template:
        raise ValueError("prompt_template must not be blank")
    if len(template) > 2000:
        raise ValueError("prompt_template must contain at most 2000 characters")
    variables = set(_TEMPLATE_VARIABLE_RE.findall(template))
    unknown = sorted(variables - ALLOWED_TEMPLATE_VARIABLES)
    if unknown:
        raise ValueError(f"unsupported prompt template variables: {', '.join(unknown)}")
    if "keywords" not in variables:
        raise ValueError("prompt_template must contain {{keywords}}")
    if "time_range" not in variables:
        raise ValueError("prompt_template must contain {{time_range}}")
    return template


def render_prompt(template: str, keywords: list[str], search_window_days: int) -> str:
    validated = validate_prompt_template(template)
    rendered = re.sub(
        r"{{\s*keywords\s*}}",
        "、".join(normalize_keywords(keywords)),
        validated,
    )
    rendered = re.sub(
        r"{{\s*time_range\s*}}",
        f"最近{int(search_window_days)}天",
        rendered,
    )
    return " ".join(rendered.split())


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    cron: str | None = None
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduleInput":
        if self.enabled and not self.cron:
            raise ValueError("cron is required when schedule is enabled")
        if self.cron:
            try:
                self.cron = validate_five_field_cron(self.cron)
            except CronValidationError as exc:
                raise ValueError(str(exc)) from exc
        return self


class DeliveryTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["callback", "wecom"]
    display_name: str = Field(default="", max_length=80)
    enabled: bool = True
    url: str | None = Field(default=None, max_length=2048)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_target(self) -> "DeliveryTargetInput":
        if self.type == "callback":
            if not self.url:
                raise ValueError("url is required for callback delivery")
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("callback url must be an absolute http(s) URL")
            if parsed.username or parsed.password:
                raise ValueError("callback url must not contain credentials")
            if self.session_id:
                raise ValueError("session_id is only valid for wecom delivery")
        else:
            if not self.session_id or not self.session_id.strip():
                raise ValueError("session_id is required for wecom delivery")
            self.session_id = self.session_id.strip()
            if self.url:
                raise ValueError("url is only valid for callback delivery")
        self.display_name = self.display_name.strip()
        return self


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=120)
    keyword: str = Field(default="", max_length=128)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    prompt_template: str = Field(default=PROMPT_TEMPLATE, max_length=2000)
    enabled: bool = True
    search_window_days: int = Field(default=30, ge=1, le=3650)
    sources: list[Literal["darkweb", "telegram", "web"]] = Field(
        default_factory=lambda: list(DEFAULT_SOURCES)
    )
    language: Literal["zh-CN"] = "zh-CN"
    schedule: ScheduleInput = Field(default_factory=ScheduleInput)
    deliveries: list[DeliveryTargetInput] = Field(default_factory=list, max_length=20)

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one source is required")
        return [source for source in DEFAULT_SOURCES if source in set(value)]

    @field_validator("prompt_template")
    @classmethod
    def clean_prompt_template(cls, value: str) -> str:
        return validate_prompt_template(value)

    @model_validator(mode="after")
    def normalize(self) -> "ProfileInput":
        values = list(self.keywords)
        if not values and self.keyword:
            values = [self.keyword]
        self.keywords = normalize_keywords(values)
        self.keyword = self.keywords[0]
        self.name = self.name.strip() or f"{self.keyword}威胁情报"
        return self

    def rendered_prompt(self) -> str:
        return render_prompt(self.prompt_template, self.keywords, self.search_window_days)


class ProfileUpdate(ProfileInput):
    pass


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, min_length=1, max_length=128)
    keywords: list[str] | None = Field(default=None, max_length=30)
    search_window_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def normalize(self) -> "RunRequest":
        if self.keywords is not None:
            self.keywords = normalize_keywords(self.keywords)
            self.keyword = self.keywords[0]
        elif self.keyword is not None:
            self.keyword = normalize_keyword(self.keyword)
            self.keywords = [self.keyword]
        return self
