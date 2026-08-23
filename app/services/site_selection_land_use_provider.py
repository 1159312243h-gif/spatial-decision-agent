from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from practice.site_selection.online_land_use import (
    CachedLandUseProvider,
    LandUseFeatureCache,
    LandUseProvider,
    OverpassLandUseProvider,
)


@dataclass
class ConfiguredLandUseProvider:
    provider: LandUseProvider | None
    http_client: Any | None = None

    def close(self) -> None:
        if self.http_client is None:
            return
        close = getattr(self.http_client, "close", None)
        if callable(close):
            close()
        self.http_client = None


def build_configured_land_use_provider(
    environ: Mapping[str, str],
    *,
    cache_store: LandUseFeatureCache | None = None,
    http_client_factory: Callable[..., Any] = httpx.Client,
) -> ConfiguredLandUseProvider:
    mode = environ.get("SITE_SELECTION_LAND_USE_PROVIDER", "auto").strip().lower()
    if mode in {"", "disabled", "none"}:
        return ConfiguredLandUseProvider(provider=None)
    if mode not in {"auto", "overpass"}:
        raise ValueError(
            "SITE_SELECTION_LAND_USE_PROVIDER 只能是 auto、overpass 或 disabled"
        )

    client_options: dict[str, Any] = {
        "headers": {
            "User-Agent": environ.get(
                "SITE_SELECTION_POI_USER_AGENT",
                "ai-agent-learning-site-selection/1.0",
            ).strip()
        }
    }
    proxy_url = environ.get("SITE_SELECTION_POI_PROXY_URL", "").strip()
    if proxy_url:
        client_options["proxy"] = proxy_url
    client = http_client_factory(**client_options)
    try:
        provider: LandUseProvider = OverpassLandUseProvider(
            client,
            endpoint=environ.get(
                "SITE_SELECTION_LAND_USE_OVERPASS_ENDPOINT",
                environ.get(
                    "SITE_SELECTION_OVERPASS_ENDPOINT",
                    "https://overpass-api.de/api/interpreter",
                ),
            ).strip(),
            timeout_seconds=_positive_float(
                environ,
                "SITE_SELECTION_LAND_USE_TIMEOUT_SECONDS",
                15,
            ),
            max_features=_positive_int(
                environ,
                "SITE_SELECTION_LAND_USE_MAX_FEATURES",
                500,
            ),
            cache_version=environ.get(
                "SITE_SELECTION_LAND_USE_CACHE_VERSION",
                "osm-land-use-v1",
            ).strip(),
        )
        if cache_store is not None:
            provider = CachedLandUseProvider(
                provider,
                cache_store,
                cache_scope=getattr(provider, "cache_token", "overpass-land"),
            )
    except Exception:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        raise
    return ConfiguredLandUseProvider(provider=provider, http_client=client)


def _positive_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正整数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def _positive_float(
    environ: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正数")
    return value
