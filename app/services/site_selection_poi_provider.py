from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from practice.site_selection.online_poi_adapters import (
    AmapPOIAdapter,
    CachedPOIAdapter,
    CategoryPartitioningPOIAdapter,
    FallbackPOIAdapter,
    FixedIntervalRateLimiter,
    GCJ02CoordinateTransformer,
    OverpassPOIAdapter,
    OverpassTagFilter,
    PostGISPOIRecoveryAdapter,
    PersistingPOIAdapter,
    RetryingCircuitBreakerPOIAdapter,
)
from practice.site_selection.poi import POIFeatureSet
from practice.site_selection.poi_adapters import FixturePOIAdapter, POISourceAdapter
from practice.site_selection.poi_normalizer import POINormalizer, RawPOI
from practice.site_selection.storage.poi_repository import PostgresPOIRepository


class SiteSelectionPOIProviderConfigurationError(ValueError):
    """Raised when an explicitly selected online POI source is incomplete."""


@dataclass
class ConfiguredPOIProvider:
    requested_mode: str
    resolved_mode: str
    adapter: POISourceAdapter
    http_client: Any | None = None

    def close(self) -> None:
        close = getattr(self.http_client, "close", None)
        if callable(close):
            close()


OVERPASS_CATEGORY_FILTERS: dict[str, OverpassTagFilter] = {
    # Keep the original business semantics.  The query planner below limits
    # element types instead of replacing station/stop tags with narrower tags
    # that are sparsely mapped in some regions.
    "地铁站": OverpassTagFilter(key="railway", value="station"),
    "公交站": OverpassTagFilter(key="highway", value="bus_stop"),
    "住宅小区": OverpassTagFilter(key="landuse", value="residential"),
    "公寓": OverpassTagFilter(key="building", value="apartments"),
    "写字楼": OverpassTagFilter(key="building", value="office"),
    "产业园": OverpassTagFilter(key="landuse", value="industrial"),
    "餐厅": OverpassTagFilter(key="amenity", value="restaurant"),
    "咖啡馆": OverpassTagFilter(key="amenity", value="cafe"),
    "书店": OverpassTagFilter(key="shop", value="books"),
    "公园": OverpassTagFilter(key="leisure", value="park"),
    "便利店": OverpassTagFilter(key="shop", value="convenience"),
    "超市": OverpassTagFilter(key="shop", value="supermarket"),
    "停车场": OverpassTagFilter(key="amenity", value="parking"),
    "医院": OverpassTagFilter(key="amenity", value="hospital"),
    "学校": OverpassTagFilter(key="amenity", value="school"),
    "文化场馆": OverpassTagFilter(key="amenity", value="arts_centre"),
    "购物中心": OverpassTagFilter(key="shop", value="mall"),
    "百货商场": OverpassTagFilter(key="shop", value="department_store"),
    "高速收费站": OverpassTagFilter(key="barrier", value="toll_booth"),
    "高速出入口": OverpassTagFilter(key="highway", value="motorway_junction"),
    "铁路货运站": OverpassTagFilter(key="railway", value="yard"),
    "港口": OverpassTagFilter(key="industrial", value="port"),
    "货运机场": OverpassTagFilter(key="aeroway", value="aerodrome"),
    "物流公司": OverpassTagFilter(key="office", value="logistics"),
    "快递网点": OverpassTagFilter(key="amenity", value="post_office"),
    "工业园": OverpassTagFilter(key="landuse", value="industrial"),
    "仓储基地": OverpassTagFilter(key="building", value="warehouse"),
    "加油站": OverpassTagFilter(key="amenity", value="fuel"),
    "充电站": OverpassTagFilter(key="amenity", value="charging_station"),
    "货车维修": OverpassTagFilter(key="shop", value="car_repair"),
}

# OSM point tags should not force Overpass to scan relation geometries. Most
# remaining business categories are represented by nodes or ways; omitting
# relations keeps the live query bounded while preserving usable POI centers.
OVERPASS_CATEGORY_ELEMENT_TYPES: dict[str, tuple[str, ...]] = {
    category: (
        ("node",)
        if category in {"高速收费站", "高速出入口"}
        else ("node", "way")
    )
    for category in OVERPASS_CATEGORY_FILTERS
}


def build_configured_poi_provider(
    environ: Mapping[str, str],
    fixture_adapter: FixturePOIAdapter,
    *,
    cache_store: Any,
    engine: Any,
    http_client_factory: Callable[..., Any] = httpx.Client,
) -> ConfiguredPOIProvider:
    requested_mode = environ.get(
        "SITE_SELECTION_POI_PROVIDER",
        "fixture",
    ).strip().lower()
    if requested_mode not in {"fixture", "auto", "amap", "overpass"}:
        raise SiteSelectionPOIProviderConfigurationError(
            "SITE_SELECTION_POI_PROVIDER 只能是 fixture、auto、amap 或 overpass"
        )
    amap_api_key = environ.get("AMAP_API_KEY", "").strip()
    resolved_mode = requested_mode
    if requested_mode == "auto":
        resolved_mode = "amap" if amap_api_key else "overpass"
    if resolved_mode == "fixture":
        return ConfiguredPOIProvider(
            requested_mode=requested_mode,
            resolved_mode=resolved_mode,
            adapter=fixture_adapter,
        )
    if resolved_mode == "amap" and not amap_api_key:
        raise SiteSelectionPOIProviderConfigurationError(
            "选择 amap POI Provider 时必须配置 AMAP_API_KEY"
        )

    http_client_options: dict[str, Any] = {
        "headers": {
            "User-Agent": environ.get(
                "SITE_SELECTION_POI_USER_AGENT",
                "ai-agent-learning-site-selection/1.0",
            )
        },
        "follow_redirects": True,
    }
    proxy_url = environ.get("SITE_SELECTION_POI_PROXY_URL", "").strip()
    if proxy_url:
        http_client_options["proxy"] = proxy_url
    http_client = http_client_factory(
        **http_client_options,
    )
    timeout_seconds = _positive_float(
        environ,
        "SITE_SELECTION_POI_TIMEOUT_SECONDS",
        15,
    )
    rate_limiter = FixedIntervalRateLimiter(
        _positive_float(
            environ,
            "SITE_SELECTION_POI_REQUESTS_PER_SECOND",
            1,
        )
    )
    if resolved_mode == "amap":
        primary: POISourceAdapter = AmapPOIAdapter(
            amap_api_key,
            http_client,
            GCJ02CoordinateTransformer(),
            rate_limiter=rate_limiter,
            max_pages_per_search=_positive_int(
                environ,
                "SITE_SELECTION_AMAP_MAX_PAGES_PER_SEARCH",
                2,
            ),
            max_categories_per_query=_positive_int(
                environ,
                "SITE_SELECTION_AMAP_MAX_CATEGORIES_PER_QUERY",
                3,
            ),
            timeout_seconds=timeout_seconds,
            cache_version=environ.get(
                "SITE_SELECTION_AMAP_CACHE_VERSION",
                "amap-v3-live-v1",
            ),
        )
    else:
        primary = OverpassPOIAdapter(
            http_client,
            OVERPASS_CATEGORY_FILTERS,
            category_element_types=OVERPASS_CATEGORY_ELEMENT_TYPES,
            endpoint=environ.get(
                "SITE_SELECTION_OVERPASS_ENDPOINT",
                "https://overpass-api.de/api/interpreter",
            ),
            fallback_endpoints=_comma_separated_values(
                environ.get(
                    "SITE_SELECTION_OVERPASS_FALLBACK_ENDPOINTS",
                    "",
                )
            ),
            rate_limiter=rate_limiter,
            timeout_seconds=timeout_seconds,
            max_categories_per_query=_positive_int(
                environ,
                "SITE_SELECTION_OVERPASS_MAX_CATEGORIES_PER_QUERY",
                3,
            ),
            cache_version=environ.get(
                "SITE_SELECTION_OVERPASS_CACHE_VERSION",
                "overpass-live-v1",
            ),
        )

    reliable: POISourceAdapter = RetryingCircuitBreakerPOIAdapter(
        primary,
        max_attempts=_positive_int(
            environ,
            "SITE_SELECTION_POI_MAX_ATTEMPTS",
            2,
        ),
        failure_threshold=_positive_int(
            environ,
            "SITE_SELECTION_POI_FAILURE_THRESHOLD",
            12,
        ),
        recovery_timeout_seconds=_positive_float(
            environ,
            "SITE_SELECTION_POI_RECOVERY_SECONDS",
            30,
        ),
        base_backoff_seconds=_positive_float(
            environ,
            "SITE_SELECTION_POI_RETRY_BASE_SECONDS",
            2,
        ),
        max_backoff_seconds=_positive_float(
            environ,
            "SITE_SELECTION_POI_RETRY_MAX_SECONDS",
            8,
        ),
    )
    active: POISourceAdapter = reliable
    if _boolean(
        environ,
        "SITE_SELECTION_POI_POSTGIS_RECOVERY_ENABLED",
        True,
    ):
        # Recover only previously persisted real OSM rows before considering
        # the explicit Fixture fallback.  This does not enable Fixture mode.
        active = PostGISPOIRecoveryAdapter(active, engine)
    fallback_enabled = _boolean(
        environ,
        "SITE_SELECTION_POI_FALLBACK_ENABLED",
        True,
    )
    if fallback_enabled:
        active = FallbackPOIAdapter(active, fixture_adapter)
    if _boolean(environ, "SITE_SELECTION_POI_PERSIST_ENABLED", True):
        active = PersistingPOIAdapter(
            active,
            _PostGISPOIFeatureSink(engine),
        )
    cache_scope = (
        f"workflow:{resolved_mode}:"
        f"{getattr(primary, 'cache_token', type(primary).__name__)}"
    )
    active = CachedPOIAdapter(
        active,
        cache_store,
        cache_scope=cache_scope,
    )
    if resolved_mode == "overpass" and not fallback_enabled:
        active = CategoryPartitioningPOIAdapter(active)
        # Keep an outer group cache for compatibility with existing Redis
        # entries, while the inner cache stores successful category queries.
        active = CachedPOIAdapter(
            active,
            cache_store,
            cache_scope=cache_scope,
        )
    return ConfiguredPOIProvider(
        requested_mode=requested_mode,
        resolved_mode=resolved_mode,
        adapter=active,
        http_client=http_client,
    )


class _PostGISPOIFeatureSink:
    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._normalizer = POINormalizer()

    def save(self, feature_set: POIFeatureSet) -> None:
        if feature_set.source.is_synthetic or not feature_set.records:
            return
        normalized = self._normalizer.normalize_many(
            RawPOI(
                source=feature_set.source.provider.value,
                source_id=str(
                    record.attributes.get("source_id") or record.poi_id
                ),
                name=record.name,
                category=record.category,
                longitude=record.longitude,
                latitude=record.latitude,
                source_crs="EPSG:4326",
                address=(
                    str(record.attributes["address"])
                    if record.attributes.get("address")
                    else None
                ),
                fetched_at=feature_set.source.queried_at,
                raw_payload={
                    "dataset_id": feature_set.source.dataset_id,
                    "dataset_version": feature_set.source.dataset_version,
                    "upstream_source_crs": record.attributes.get("source_crs"),
                    **record.attributes,
                },
            )
            for record in feature_set.records
        )
        with self._engine.begin() as connection:
            PostgresPOIRepository(connection).upsert_many(normalized)


def _positive_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    try:
        value = int(environ.get(name, str(default)))
    except ValueError as exc:
        raise SiteSelectionPOIProviderConfigurationError(
            f"{name} 必须是正整数"
        ) from exc
    if value <= 0:
        raise SiteSelectionPOIProviderConfigurationError(
            f"{name} 必须是正整数"
        )
    return value


def _comma_separated_values(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in value.split(",")
            if item.strip()
        )
    )


def _positive_float(
    environ: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    try:
        value = float(environ.get(name, str(default)))
    except ValueError as exc:
        raise SiteSelectionPOIProviderConfigurationError(
            f"{name} 必须是正数"
        ) from exc
    if value <= 0:
        raise SiteSelectionPOIProviderConfigurationError(
            f"{name} 必须是正数"
        )
    return value


def _boolean(
    environ: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SiteSelectionPOIProviderConfigurationError(
        f"{name} 必须是 true 或 false"
    )
