from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import NonEmptyString
from .poi import POIFeatureSet, POIProvider, POIQuery, POIRecord, POISourceMeta
from .poi_adapters import POISourceAdapter, haversine_distance_m
from .poi_service import calculate_poi_metrics


class POIAdapterError(RuntimeError):
    """Base error for online POI adapters."""


class POIAvailabilityError(POIAdapterError):
    """Transient upstream failure eligible for an explicit fallback."""


class POIRateLimitError(POIAvailabilityError):
    """Raised when an upstream provider rejects a request for quota reasons."""


class POIUpstreamError(POIAvailabilityError):
    """Raised for network or upstream service failures."""


class POIResponseError(POIAdapterError):
    """Raised when an upstream payload violates the reviewed contract."""


class POICircuitOpenError(POIAvailabilityError):
    """Raised while a provider circuit is open after repeated failures."""


class HTTPResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class POIHTTPClient(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        timeout: float,
    ) -> HTTPResponse: ...

    def post(
        self,
        url: str,
        *,
        data: Mapping[str, Any],
        timeout: float,
    ) -> HTTPResponse: ...


class CoordinateTransformer(Protocol):
    def wgs84_to_gcj02(
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]: ...

    def gcj02_to_wgs84(
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]: ...


class RequestRateLimiter(Protocol):
    def acquire(self) -> None: ...


class POIFeatureCache(Protocol):
    def get_cached_poi(
        self,
        query: POIQuery,
        *,
        cache_scope: str,
    ) -> POIFeatureSet | None: ...

    def save_cached_poi(
        self,
        feature_set: POIFeatureSet,
        *,
        cache_scope: str,
    ) -> None: ...


class POIFeatureSink(Protocol):
    def save(self, feature_set: POIFeatureSet) -> None: ...


class NoopRateLimiter:
    def acquire(self) -> None:
        return None


class FixedIntervalRateLimiter:
    """Thread-safe client-side limiter for provider request pacing."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("POI 请求速率必须大于 0")
        self._interval = 1 / requests_per_second
        self._monotonic = monotonic
        self._sleep = sleep
        self._next_allowed_at = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._monotonic()
            delay = self._next_allowed_at - now
            if delay > 0:
                self._sleep(delay)
                now = self._monotonic()
            self._next_allowed_at = max(now, self._next_allowed_at) + self._interval


class RetryingCircuitBreakerPOIAdapter:
    """Bound retries and temporarily isolate a repeatedly failing POI source."""

    def __init__(
        self,
        primary: POISourceAdapter,
        *,
        max_attempts: int = 2,
        failure_threshold: int = 2,
        recovery_timeout_seconds: float = 30,
        base_backoff_seconds: float = 0.1,
        max_backoff_seconds: float = 1,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if primary is None:
            raise ValueError("reliable POI adapter requires a primary adapter")
        if max_attempts <= 0 or failure_threshold <= 0:
            raise ValueError("retry attempts and failure threshold must be positive")
        if recovery_timeout_seconds <= 0:
            raise ValueError("circuit recovery timeout must be positive")
        if base_backoff_seconds < 0 or max_backoff_seconds < base_backoff_seconds:
            raise ValueError("retry backoff bounds are invalid")
        self._primary = primary
        self._max_attempts = max_attempts
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    @property
    def provider(self) -> POIProvider:
        return _provider_of(self._primary)

    @property
    def cache_token(self) -> str:
        primary = getattr(self._primary, "cache_token", type(self._primary).__name__)
        return (
            f"reliable:{primary}:attempts={self._max_attempts}:"
            f"threshold={self._failure_threshold}"
        )

    @property
    def max_categories_per_query(self) -> int | None:
        return _max_categories_per_query(self._primary)

    @property
    def circuit_open(self) -> bool:
        with self._lock:
            return self._monotonic() < self._open_until

    def search(self, query: POIQuery) -> POIFeatureSet:
        with self._lock:
            if self._monotonic() < self._open_until:
                raise POICircuitOpenError("POI provider circuit is open")

        for attempt in range(1, self._max_attempts + 1):
            try:
                result = self._primary.search(query)
            except POIAvailabilityError:
                if attempt < self._max_attempts:
                    delay = min(
                        self._base_backoff_seconds * (2 ** (attempt - 1)),
                        self._max_backoff_seconds,
                    )
                    if delay:
                        self._sleep(delay)
                    continue
                self._record_failure()
                raise
            self._record_success()
            return result
        raise RuntimeError("unreachable retry state")

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = 0.0

    def _record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open_until = (
                    self._monotonic() + self._recovery_timeout_seconds
                )


class CachedPOIAdapter:
    """Reuse normalized Provider results while preserving the active query identity."""

    def __init__(
        self,
        delegate: POISourceAdapter,
        cache: POIFeatureCache,
        *,
        cache_scope: str,
    ) -> None:
        if delegate is None or cache is None:
            raise ValueError("缓存 POI Adapter 必须配置 delegate 和 cache")
        normalized_scope = cache_scope.strip()
        if not normalized_scope:
            raise ValueError("缓存 POI Adapter 的 cache_scope 不能为空")
        self._delegate = delegate
        self._cache = cache
        self._cache_scope = normalized_scope

    @property
    def cache_token(self) -> str:
        delegate_token = getattr(
            self._delegate,
            "cache_token",
            type(self._delegate).__name__,
        )
        return f"cached:{self._cache_scope}:{delegate_token}"

    @property
    def max_categories_per_query(self) -> int | None:
        return _max_categories_per_query(self._delegate)

    def search(self, query: POIQuery) -> POIFeatureSet:
        cached = self._cache.get_cached_poi(
            query,
            cache_scope=self._cache_scope,
        )
        if cached is not None:
            return cached.model_copy(
                deep=True,
                update={
                    "query": query.model_copy(deep=True),
                    "source": cached.source.model_copy(
                        deep=True,
                        update={"cache_hit": True},
                    ),
                },
            )
        result = self._delegate.search(query)
        if result.query != query:
            raise ValueError("POI delegate 返回了与请求不一致的查询")
        # A fallback is a temporary availability result, not a durable answer
        # for the online cache key. Caching it would suppress upstream recovery.
        if result.source.fallback_from is None:
            self._cache.save_cached_poi(
                result,
                cache_scope=self._cache_scope,
            )
        return result


class PersistingPOIAdapter:
    """Persist a successful normalized response before returning it to the workflow."""

    def __init__(
        self,
        delegate: POISourceAdapter,
        sink: POIFeatureSink,
    ) -> None:
        if delegate is None or sink is None:
            raise ValueError("入库 POI Adapter 必须配置 delegate 和 sink")
        self._delegate = delegate
        self._sink = sink

    @property
    def cache_token(self) -> str:
        delegate_token = getattr(
            self._delegate,
            "cache_token",
            type(self._delegate).__name__,
        )
        return f"persisted:{delegate_token}"

    @property
    def max_categories_per_query(self) -> int | None:
        return _max_categories_per_query(self._delegate)

    def search(self, query: POIQuery) -> POIFeatureSet:
        result = self._delegate.search(query)
        if result.query != query:
            raise ValueError("POI delegate 返回了与请求不一致的查询")
        self._sink.save(result)
        return result


class GCJ02CoordinateTransformer:
    """Explicit WGS84/GCJ-02 conversion for mainland China coordinates."""

    _A = 6_378_245.0
    _EE = 0.006693421622965943

    def wgs84_to_gcj02(
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]:
        _validate_coordinate(longitude, latitude)
        if _outside_mainland_china(longitude, latitude):
            return longitude, latitude
        delta_longitude, delta_latitude = self._delta(longitude, latitude)
        return longitude + delta_longitude, latitude + delta_latitude

    def gcj02_to_wgs84(
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]:
        _validate_coordinate(longitude, latitude)
        if _outside_mainland_china(longitude, latitude):
            return longitude, latitude
        guess_longitude, guess_latitude = longitude, latitude
        for _ in range(10):
            mapped_longitude, mapped_latitude = self.wgs84_to_gcj02(
                guess_longitude,
                guess_latitude,
            )
            error_longitude = mapped_longitude - longitude
            error_latitude = mapped_latitude - latitude
            guess_longitude -= error_longitude
            guess_latitude -= error_latitude
            if max(abs(error_longitude), abs(error_latitude)) < 1e-8:
                break
        return guess_longitude, guess_latitude

    def _delta(
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]:
        shifted_longitude = longitude - 105.0
        shifted_latitude = latitude - 35.0
        latitude_delta = _transform_latitude(
            shifted_longitude,
            shifted_latitude,
        )
        longitude_delta = _transform_longitude(
            shifted_longitude,
            shifted_latitude,
        )
        radian_latitude = latitude / 180.0 * math.pi
        sin_latitude = math.sin(radian_latitude)
        magic = 1 - self._EE * sin_latitude * sin_latitude
        sqrt_magic = math.sqrt(magic)
        latitude_delta = (
            latitude_delta
            * 180.0
            / ((self._A * (1 - self._EE)) / (magic * sqrt_magic) * math.pi)
        )
        longitude_delta = (
            longitude_delta
            * 180.0
            / (self._A / sqrt_magic * math.cos(radian_latitude) * math.pi)
        )
        return longitude_delta, latitude_delta


class AmapPOIAdapter:
    endpoint = "https://restapi.amap.com/v3/place/around"

    def __init__(
        self,
        api_key: str,
        http_client: POIHTTPClient,
        coordinate_transformer: CoordinateTransformer,
        *,
        rate_limiter: RequestRateLimiter | None = None,
        page_size: int = 25,
        max_pages_per_search: int | None = None,
        max_categories_per_query: int = 3,
        timeout_seconds: float = 5,
        cache_version: str = "amap-v3",
        category_aliases: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("高德 POI Adapter 必须显式配置 API Key")
        if http_client is None or coordinate_transformer is None:
            raise ValueError("高德 POI Adapter 必须配置 HTTP Client 和坐标转换器")
        if page_size <= 0 or page_size > 25:
            raise ValueError("高德 POI 分页大小必须在 1 到 25 之间")
        if max_pages_per_search is not None and max_pages_per_search <= 0:
            raise ValueError("高德 POI 单次查询页数预算必须大于 0")
        if max_categories_per_query <= 0:
            raise ValueError("高德 POI 单次查询类别预算必须大于 0")
        if timeout_seconds <= 0:
            raise ValueError("高德 POI 超时必须大于 0")
        if not cache_version.strip():
            raise ValueError("高德 POI cache_version 不能为空")
        self._api_key = api_key
        self._http_client = http_client
        self._transformer = coordinate_transformer
        self._rate_limiter = rate_limiter or NoopRateLimiter()
        self._page_size = page_size
        self._max_pages_per_search = max_pages_per_search
        self._max_categories_per_query = max_categories_per_query
        self._timeout_seconds = timeout_seconds
        self._cache_version = cache_version.strip()
        self._category_aliases = dict(category_aliases or {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def cache_token(self) -> str:
        page_budget = self._max_pages_per_search or "unbounded"
        return (
            f"amap:{self._cache_version}:pages={page_budget}:"
            f"categories={self._max_categories_per_query}"
        )

    @property
    def max_categories_per_query(self) -> int:
        return self._max_categories_per_query

    def search(self, query: POIQuery) -> POIFeatureSet:
        center_longitude, center_latitude = self._transformer.wgs84_to_gcj02(
            query.longitude,
            query.latitude,
        )
        records_by_id: dict[str, POIRecord] = {}
        provider_record_count: int | None = None
        requested_pages = math.ceil(query.limit / self._page_size)
        max_pages = requested_pages
        if self._max_pages_per_search is not None:
            max_pages = min(max_pages, self._max_pages_per_search)
        last_page_size = 0
        for page in range(1, max_pages + 1):
            self._rate_limiter.acquire()
            payload = self._request_page(
                query,
                center_longitude=center_longitude,
                center_latitude=center_latitude,
                page=page,
            )
            raw_count = payload.get("count")
            if raw_count is not None:
                try:
                    parsed_count = int(raw_count)
                except (TypeError, ValueError) as exc:
                    raise POIResponseError("高德 POI count 无效") from exc
                if parsed_count < 0:
                    raise POIResponseError("高德 POI count 不能为负数")
                provider_record_count = max(
                    provider_record_count or 0,
                    parsed_count,
                )
            pois = payload.get("pois")
            if not isinstance(pois, list):
                raise POIResponseError("高德 POI 响应缺少 pois 列表")
            last_page_size = len(pois)
            if not pois:
                break
            for raw in pois:
                record = self._parse_record(raw, query)
                records_by_id.setdefault(record.poi_id, record)
                if len(records_by_id) >= query.limit:
                    break
            if len(records_by_id) >= query.limit or len(pois) < self._page_size:
                break

        records = sorted(
            records_by_id.values(),
            key=lambda item: (item.distance_m or 0, item.poi_id),
        )[: query.limit]
        page_budget_exhausted = (
            max_pages < requested_pages
            and last_page_size >= self._page_size
            and len(records_by_id) < query.limit
        )
        available_record_count = max(
            provider_record_count or 0,
            len(records_by_id) + int(page_budget_exhausted),
        )
        source = POISourceMeta(
            provider=POIProvider.AMAP,
            dataset_id="amap-place-around",
            dataset_version=self._cache_version,
            queried_at=self._clock(),
            crs="EPSG:4326",
            record_count=len(records),
            available_record_count=available_record_count,
            is_truncated=available_record_count > len(records),
        )
        return POIFeatureSet(
            query=query.model_copy(deep=True),
            records=records,
            source=source,
            metrics=calculate_poi_metrics(query, records),
        )

    def _request_page(
        self,
        query: POIQuery,
        *,
        center_longitude: float,
        center_latitude: float,
        page: int,
    ) -> dict[str, Any]:
        params = {
            "key": self._api_key,
            "location": f"{center_longitude:.8f},{center_latitude:.8f}",
            "keywords": "|".join(query.categories),
            "radius": query.radius_m,
            "offset": self._page_size,
            "page": page,
            "extensions": "all",
        }
        try:
            response = self._http_client.get(
                self.endpoint,
                params=params,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise POIUpstreamError(
                f"高德 POI 网络请求失败：{type(exc).__name__}"
            ) from exc
        if response.status_code == 429:
            raise POIRateLimitError("高德 POI 请求受到 HTTP 429 限流")
        if response.status_code >= 500:
            raise POIUpstreamError(
                f"高德 POI 服务异常：HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise POIResponseError(
                f"高德 POI 请求被拒绝：HTTP {response.status_code}"
            )
        payload = _response_json(response, provider="高德")
        if payload.get("status") != "1":
            info_code = str(payload.get("infocode", "unknown"))
            if info_code in {"10003", "10004", "10020", "10021", "10044"}:
                raise POIRateLimitError(f"高德 POI 配额受限：infocode={info_code}")
            raise POIResponseError(f"高德 POI 业务错误：infocode={info_code}")
        return payload

    def _parse_record(self, raw: Any, query: POIQuery) -> POIRecord:
        if not isinstance(raw, dict):
            raise POIResponseError("高德 POI 记录必须是对象")
        source_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        location = str(raw.get("location", "")).split(",")
        if not source_id or not name or len(location) != 2:
            raise POIResponseError("高德 POI 记录缺少 id、name 或 location")
        try:
            gcj_longitude, gcj_latitude = map(float, location)
            longitude, latitude = self._transformer.gcj02_to_wgs84(
                gcj_longitude,
                gcj_latitude,
            )
        except (TypeError, ValueError) as exc:
            raise POIResponseError("高德 POI location 无效") from exc
        category = _resolve_amap_category(
            raw,
            query.categories,
            self._category_aliases,
        )
        return POIRecord(
            poi_id=f"amap:{source_id}",
            name=name,
            category=category,
            longitude=longitude,
            latitude=latitude,
            distance_m=haversine_distance_m(
                query.longitude,
                query.latitude,
                longitude,
                latitude,
            ),
            attributes={
                "source": "amap",
                "source_id": source_id,
                "source_crs": "GCJ-02",
                "source_longitude": gcj_longitude,
                "source_latitude": gcj_latitude,
                "address": raw.get("address"),
                "type": raw.get("type"),
                "typecode": raw.get("typecode"),
            },
        )


class OverpassTagFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[A-Za-z0-9_:.-]+$")
    value: str = Field(pattern=r"^[A-Za-z0-9_:.-]+$")


class OverpassPOIAdapter:
    def __init__(
        self,
        http_client: POIHTTPClient,
        category_filters: Mapping[str, OverpassTagFilter],
        *,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        rate_limiter: RequestRateLimiter | None = None,
        timeout_seconds: float = 15,
        max_categories_per_query: int = 3,
        cache_version: str = "overpass-live-v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if http_client is None:
            raise ValueError("Overpass POI Adapter 必须配置 HTTP Client")
        if not category_filters:
            raise ValueError("Overpass POI Adapter 至少需要一个类别标签映射")
        if not endpoint.startswith("https://"):
            raise ValueError("Overpass endpoint 必须使用 HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("Overpass POI 超时必须大于 0")
        if max_categories_per_query <= 0:
            raise ValueError("Overpass 单次查询类别预算必须大于 0")
        if not cache_version.strip():
            raise ValueError("Overpass cache_version 不能为空")
        self._http_client = http_client
        self._category_filters = {
            category.strip(): tag.model_copy(deep=True)
            for category, tag in category_filters.items()
            if category.strip()
        }
        if len(self._category_filters) != len(category_filters):
            raise ValueError("Overpass 类别名称不能为空")
        self._endpoint = endpoint
        self._rate_limiter = rate_limiter or NoopRateLimiter()
        self._timeout_seconds = timeout_seconds
        self._max_categories_per_query = max_categories_per_query
        self._cache_version = cache_version.strip()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def cache_token(self) -> str:
        return (
            f"overpass:{self._cache_version}:"
            f"categories={self._max_categories_per_query}"
        )

    @property
    def max_categories_per_query(self) -> int:
        return self._max_categories_per_query

    def search(self, query: POIQuery) -> POIFeatureSet:
        missing = sorted(set(query.categories) - self._category_filters.keys())
        if missing:
            raise ValueError(
                "Overpass 缺少类别标签映射：" + ", ".join(missing)
            )
        statement = self._build_query(query)
        self._rate_limiter.acquire()
        try:
            response = self._http_client.post(
                self._endpoint,
                data={"data": statement},
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise POIUpstreamError(
                f"Overpass 网络请求失败：{type(exc).__name__}"
            ) from exc
        if response.status_code == 429:
            raise POIRateLimitError("Overpass 请求受到 HTTP 429 限流")
        if response.status_code >= 500:
            raise POIUpstreamError(
                f"Overpass 服务异常：HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise POIResponseError(
                f"Overpass 请求被拒绝：HTTP {response.status_code}"
            )
        payload = _response_json(response, provider="Overpass")
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise POIResponseError("Overpass 响应缺少 elements 列表")

        records_by_id: dict[str, POIRecord] = {}
        for element in elements:
            record = self._parse_element(element, query)
            if record is not None:
                records_by_id.setdefault(record.poi_id, record)
        records = sorted(
            records_by_id.values(),
            key=lambda item: (item.distance_m or 0, item.poi_id),
        )[: query.limit]
        available_record_count = len(records_by_id)
        source = POISourceMeta(
            provider=POIProvider.OSM,
            dataset_id="openstreetmap-overpass",
            dataset_version=self._cache_version,
            queried_at=self._clock(),
            crs="EPSG:4326",
            record_count=len(records),
            available_record_count=available_record_count,
            is_truncated=available_record_count > len(records),
        )
        return POIFeatureSet(
            query=query.model_copy(deep=True),
            records=records,
            source=source,
            metrics=calculate_poi_metrics(query, records),
        )

    def _build_query(self, query: POIQuery) -> str:
        clauses = []
        for category in query.categories:
            tag = self._category_filters[category]
            for element_type in ("node", "way", "relation"):
                clauses.append(
                    f'{element_type}["{tag.key}"="{tag.value}"]'
                    f"(around:{query.radius_m},{query.latitude:.8f},"
                    f"{query.longitude:.8f});"
                )
        return "[out:json][timeout:25];(" + "".join(clauses) + ");out center tags;"

    def _parse_element(
        self,
        element: Any,
        query: POIQuery,
    ) -> POIRecord | None:
        if not isinstance(element, dict):
            raise POIResponseError("Overpass element 必须是对象")
        element_type = str(element.get("type", "")).strip()
        element_id = str(element.get("id", "")).strip()
        tags = element.get("tags") or {}
        center = element.get("center") or element
        if not element_type or not element_id or not isinstance(tags, dict):
            raise POIResponseError("Overpass element 缺少 type、id 或 tags")
        try:
            latitude = float(center["lat"])
            longitude = float(center["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise POIResponseError("Overpass element 缺少有效中心坐标") from exc
        distance_m = haversine_distance_m(
            query.longitude,
            query.latitude,
            longitude,
            latitude,
        )
        if distance_m > query.radius_m:
            return None
        category = _resolve_overpass_category(
            tags,
            query.categories,
            self._category_filters,
        )
        if category is None:
            return None
        name = str(tags.get("name") or f"OSM {element_type} {element_id}")
        return POIRecord(
            poi_id=f"osm:{element_type}:{element_id}",
            name=name,
            category=category,
            longitude=longitude,
            latitude=latitude,
            distance_m=distance_m,
            attributes={
                "source": "openstreetmap",
                "source_id": f"{element_type}/{element_id}",
                "source_crs": "EPSG:4326",
                "tags": tags,
            },
        )


class FallbackPOIAdapter:
    """Use Fixture only for explicit upstream availability failures."""

    def __init__(
        self,
        primary: POISourceAdapter,
        fallback: POISourceAdapter,
    ) -> None:
        if primary is None or fallback is None:
            raise ValueError("POI 降级 Adapter 必须配置 primary 和 fallback")
        self._primary = primary
        self._fallback = fallback

    @property
    def cache_token(self) -> str:
        primary = getattr(self._primary, "cache_token", type(self._primary).__name__)
        fallback = getattr(self._fallback, "cache_token", type(self._fallback).__name__)
        return f"fallback:{primary}:{fallback}"

    @property
    def max_categories_per_query(self) -> int | None:
        return _max_categories_per_query(self._primary)

    def search(self, query: POIQuery) -> POIFeatureSet:
        try:
            return self._primary.search(query)
        except POIAvailabilityError as exc:
            result = self._fallback.search(query)
            source_data = result.source.model_dump()
            source_data.update(
                fallback_from=_provider_of(self._primary),
                fallback_reason=type(exc).__name__,
            )
            source = POISourceMeta.model_validate(source_data)
            return result.model_copy(deep=True, update={"source": source})


def _provider_of(adapter: POISourceAdapter) -> POIProvider:
    provider = getattr(adapter, "provider", None)
    if isinstance(provider, POIProvider):
        return provider
    if isinstance(adapter, AmapPOIAdapter):
        return POIProvider.AMAP
    if isinstance(adapter, OverpassPOIAdapter):
        return POIProvider.OSM
    raise ValueError("无法确定 primary POI Adapter 的 provider")


def _max_categories_per_query(adapter: POISourceAdapter) -> int | None:
    value = getattr(adapter, "max_categories_per_query", None)
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ValueError("POI Adapter 类别预算必须是正整数")
    return value


def _response_json(response: HTTPResponse, *, provider: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise POIResponseError(f"{provider} 响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise POIResponseError(f"{provider} JSON 顶层必须是对象")
    return payload


def _resolve_amap_category(
    raw: dict[str, Any],
    requested_categories: list[str],
    aliases: Mapping[str, str],
) -> str:
    raw_type = str(raw.get("type", "")).strip()
    type_code = str(raw.get("typecode", "")).strip()
    for key in (type_code, raw_type):
        if key in aliases:
            return aliases[key]
    searchable = f"{raw.get('name', '')};{raw_type}"
    for category in requested_categories:
        if category in searchable:
            return category
    parts = [part.strip() for part in raw_type.split(";") if part.strip()]
    return parts[-1] if parts else "未分类"


def _resolve_overpass_category(
    tags: Mapping[str, Any],
    requested_categories: list[str],
    filters: Mapping[str, OverpassTagFilter],
) -> str | None:
    for category in requested_categories:
        tag = filters[category]
        if str(tags.get(tag.key, "")) == tag.value:
            return category
    return None


def _validate_coordinate(longitude: float, latitude: float) -> None:
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("坐标超出经纬度范围")


def _outside_mainland_china(longitude: float, latitude: float) -> bool:
    return not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271)


def _transform_latitude(longitude: float, latitude: float) -> float:
    value = (
        -100
        + 2 * longitude
        + 3 * latitude
        + 0.2 * latitude * latitude
        + 0.1 * longitude * latitude
        + 0.2 * math.sqrt(abs(longitude))
    )
    value += (
        20 * math.sin(6 * longitude * math.pi)
        + 20 * math.sin(2 * longitude * math.pi)
    ) * 2 / 3
    value += (
        20 * math.sin(latitude * math.pi)
        + 40 * math.sin(latitude / 3 * math.pi)
    ) * 2 / 3
    value += (
        160 * math.sin(latitude / 12 * math.pi)
        + 320 * math.sin(latitude * math.pi / 30)
    ) * 2 / 3
    return value


def _transform_longitude(longitude: float, latitude: float) -> float:
    value = (
        300
        + longitude
        + 2 * latitude
        + 0.1 * longitude * longitude
        + 0.1 * longitude * latitude
        + 0.1 * math.sqrt(abs(longitude))
    )
    value += (
        20 * math.sin(6 * longitude * math.pi)
        + 20 * math.sin(2 * longitude * math.pi)
    ) * 2 / 3
    value += (
        20 * math.sin(longitude * math.pi)
        + 40 * math.sin(longitude / 3 * math.pi)
    ) * 2 / 3
    value += (
        150 * math.sin(longitude / 12 * math.pi)
        + 300 * math.sin(longitude / 30 * math.pi)
    ) * 2 / 3
    return value
