from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from darkweb_collector.models import SiteConfig, VALID_FETCH_MODES, VALID_PROFILES
from darkweb_collector.runtime import default_config_path, output_root, project_root


REQUIRED_KEYS = {
    "site_name",
    "enabled",
    "seed_urls",
    "seed_fetch_mode",
    "detail_fetch_mode",
    "profile",
    "max_topics_per_run",
    "max_detail_pages_per_run",
    "cooldown_seconds",
    "output_dir",
    "dedupe_window_minutes",
}


class ConfigError(ValueError):
    """Raised when site configuration is invalid."""


def _load_raw_document(path: Path) -> Any:
    raw_text = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ConfigError(
                f"{path} is not valid JSON and PyYAML is not installed for YAML parsing"
            ) from exc
        return yaml.safe_load(raw_text)


def _load_raw_sites_document(path: Path | None = None) -> tuple[Path, Any]:
    resolved = path or default_config_path()
    if not resolved.exists():
        raise ConfigError(f"site config file not found: {resolved}")
    return resolved, _load_raw_document(resolved)


def _resolve_output_dir(path_value: str) -> Path:
    output_dir = Path(path_value)
    if output_dir.is_absolute():
        return output_dir
    parts = output_dir.parts
    if parts and parts[0].lower() == "output":
        return output_root().joinpath(*parts[1:]).resolve()
    return (project_root() / output_dir).resolve()


def _validate_site(payload: dict[str, Any]) -> SiteConfig:
    missing = REQUIRED_KEYS.difference(payload)
    if missing:
        missing_keys = ", ".join(sorted(missing))
        raise ConfigError(f"site config is missing required keys: {missing_keys}")

    site_name = str(payload["site_name"]).strip()
    if not site_name:
        raise ConfigError("site_name must not be empty")

    seed_urls = payload["seed_urls"]
    if not isinstance(seed_urls, list) or not seed_urls or not all(isinstance(item, str) for item in seed_urls):
        raise ConfigError(f"{site_name}: seed_urls must be a non-empty list of strings")

    seed_fetch_mode = str(payload["seed_fetch_mode"]).strip()
    detail_fetch_mode = str(payload["detail_fetch_mode"]).strip()
    profile = str(payload["profile"]).strip()
    if seed_fetch_mode not in VALID_FETCH_MODES:
        raise ConfigError(f"{site_name}: invalid seed_fetch_mode '{seed_fetch_mode}'")
    if detail_fetch_mode not in VALID_FETCH_MODES:
        raise ConfigError(f"{site_name}: invalid detail_fetch_mode '{detail_fetch_mode}'")
    if profile not in VALID_PROFILES:
        raise ConfigError(f"{site_name}: invalid profile '{profile}'")

    extras = {key: value for key, value in payload.items() if key not in REQUIRED_KEYS}
    return SiteConfig(
        site_name=site_name,
        enabled=bool(payload["enabled"]),
        seed_urls=tuple(seed_urls),
        seed_fetch_mode=seed_fetch_mode,
        detail_fetch_mode=detail_fetch_mode,
        profile=profile,
        max_topics_per_run=int(payload["max_topics_per_run"]),
        max_detail_pages_per_run=int(payload["max_detail_pages_per_run"]),
        cooldown_seconds=int(payload["cooldown_seconds"]),
        output_dir=_resolve_output_dir(str(payload["output_dir"])),
        dedupe_window_minutes=int(payload["dedupe_window_minutes"]),
        extras=extras,
    )


def load_site_configs(config_path: Path | None = None) -> list[SiteConfig]:
    path, raw_document = _load_raw_sites_document(config_path)
    raw_sites = raw_document.get("sites") if isinstance(raw_document, dict) else raw_document
    if not isinstance(raw_sites, list):
        raise ConfigError("site config must be a list or an object with a 'sites' list")

    configs: list[SiteConfig] = []
    seen: set[str] = set()
    for raw_site in raw_sites:
        if not isinstance(raw_site, dict):
            raise ConfigError("each site config entry must be an object")
        config = _validate_site(raw_site)
        if config.site_name in seen:
            raise ConfigError(f"duplicate site_name found: {config.site_name}")
        seen.add(config.site_name)
        configs.append(config)
    return configs


def get_site_config(site_name: str, config_path: Path | None = None) -> SiteConfig:
    for config in load_site_configs(config_path):
        if config.site_name == site_name:
            return config
    raise ConfigError(f"unknown site '{site_name}'")


def set_site_enabled(site_name: str, enabled: bool, config_path: Path | None = None) -> SiteConfig:
    path, raw_document = _load_raw_sites_document(config_path)
    raw_sites = raw_document.get("sites") if isinstance(raw_document, dict) else raw_document
    if not isinstance(raw_sites, list):
        raise ConfigError("site config must be a list or an object with a 'sites' list")

    updated = False
    for raw_site in raw_sites:
        if not isinstance(raw_site, dict):
            continue
        if str(raw_site.get("site_name", "")).strip() == site_name:
            raw_site["enabled"] = bool(enabled)
            updated = True
            break

    if not updated:
        raise ConfigError(f"unknown site '{site_name}'")

    if isinstance(raw_document, dict):
        serialized = raw_document
    else:
        serialized = raw_sites

    path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_site_config(site_name, path)
