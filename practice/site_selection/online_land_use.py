from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from .domain import DatasetEvidenceLevel, NonEmptyString, ProjectType
from .poi_adapters import haversine_distance_m


class LandUseProviderError(RuntimeError):
    """Base error raised by online land-use providers."""


class LandUseAvailabilityError(LandUseProviderError):
    """Transient upstream failure that may use a reviewed fallback."""


class LandUseResponseError(LandUseProviderError):
    """Upstream response violates the reviewed land-use contract."""


class LandUseHTTPResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class LandUseHTTPClient(Protocol):
    def post(
        self,
        url: str,
        *,
        data: Mapping[str, Any],
        timeout: float,
    ) -> LandUseHTTPResponse: ...


class LandUseQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: ProjectType
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> LandUseQuery:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("用地查询范围必须满足 west < east 且 south < north")
        if (
            haversine_distance_m(
                self.west,
                self.south,
                self.east,
                self.north,
            )
            > 20_000
        ):
            raise ValueError("用地查询范围对角线不能超过 20 公里")
        return self


class LandUseFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_feature_id: NonEmptyString
    name: NonEmptyString
    land_use_class: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    area_hectares: float = Field(gt=0)
    osm_tags: dict[str, Any] = Field(default_factory=dict)


class LandUseSourceMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    evidence_level: DatasetEvidenceLevel
    queried_at: datetime
    source_uri: NonEmptyString
    license: NonEmptyString
    record_count: int = Field(ge=0)
    available_record_count: int = Field(ge=0)
    cache_hit: bool = False

    @field_validator("queried_at")
    @classmethod
    def queried_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("用地查询时间必须包含时区")
        return value

    @model_validator(mode="after")
    def record_counts_are_consistent(self) -> LandUseSourceMeta:
        if self.available_record_count < self.record_count:
            raise ValueError("用地可用记录数不能小于返回记录数")
        return self


class LandUseFeatureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: LandUseQuery
    features: list[LandUseFeature]
    source: LandUseSourceMeta

    @model_validator(mode="after")
    def source_matches_features(self) -> LandUseFeatureSet:
        if self.source.record_count != len(self.features):
            raise ValueError("用地来源记录数必须等于 features 数量")
        return self


class LandUseProvider(Protocol):
    def search(self, query: LandUseQuery) -> LandUseFeatureSet: ...


class LandUseFeatureCache(Protocol):
    def get_cached_land_use(
        self,
        query: LandUseQuery,
        *,
        cache_scope: str,
    ) -> LandUseFeatureSet | None: ...

    def save_cached_land_use(
        self,
        feature_set: LandUseFeatureSet,
        *,
        cache_scope: str,
    ) -> None: ...


class CachedLandUseProvider:
    def __init__(
        self,
        delegate: LandUseProvider,
        cache: LandUseFeatureCache,
        *,
        cache_scope: str,
    ) -> None:
        if delegate is None or cache is None:
            raise ValueError("用地缓存 Provider 必须配置 delegate 和 cache")
        normalized_scope = cache_scope.strip()
        if not normalized_scope:
            raise ValueError("用地缓存 cache_scope 不能为空")
        self._delegate = delegate
        self._cache = cache
        self._cache_scope = normalized_scope

    def search(self, query: LandUseQuery) -> LandUseFeatureSet:
        cached = self._cache.get_cached_land_use(
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
            raise ValueError("用地 Provider 返回了与请求不一致的查询")
        self._cache.save_cached_land_use(
            result,
            cache_scope=self._cache_scope,
        )
        return result


class OverpassLandUseProvider:
    """Load observable OSM land-use and commercial-building polygons."""

    def __init__(
        self,
        http_client: LandUseHTTPClient,
        *,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        timeout_seconds: float = 15,
        max_features: int = 500,
        cache_version: str = "osm-land-use-v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if http_client is None:
            raise ValueError("Overpass 用地 Provider 必须配置 HTTP Client")
        if not endpoint.startswith("https://"):
            raise ValueError("Overpass 用地 endpoint 必须使用 HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("Overpass 用地超时必须大于 0")
        if max_features <= 0:
            raise ValueError("Overpass 用地最大要素数必须大于 0")
        if not cache_version.strip():
            raise ValueError("Overpass 用地 cache_version 不能为空")
        self._http_client = http_client
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._max_features = max_features
        self._cache_version = cache_version.strip()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def cache_token(self) -> str:
        return f"overpass-land:{self._cache_version}:max={self._max_features}"

    def search(self, query: LandUseQuery) -> LandUseFeatureSet:
        statement = self._build_query(query)
        try:
            response = self._http_client.post(
                self._endpoint,
                data={"data": statement},
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise LandUseAvailabilityError(
                f"Overpass 用地网络请求失败：{type(exc).__name__}"
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise LandUseAvailabilityError(
                f"Overpass 用地服务暂不可用：HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise LandUseResponseError(
                f"Overpass 用地请求被拒绝：HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise LandUseResponseError("Overpass 用地响应不是有效 JSON") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("elements"), list
        ):
            raise LandUseResponseError("Overpass 用地响应缺少 elements 列表")

        parsed_by_id = {}
        for element in payload["elements"]:
            item = _parse_overpass_polygon(element)
            if item is not None:
                parsed_by_id.setdefault(item["source_feature_id"], item)
        parsed = list(parsed_by_id.values())
        all_features = _to_land_use_features(parsed)
        in_scope_features = [
            item
            for item in all_features
            if (
                query.west <= item.longitude <= query.east
                and query.south <= item.latitude <= query.north
            )
        ]
        available_count = len(in_scope_features)
        features = in_scope_features[: self._max_features]
        queried_at = self._clock()
        return LandUseFeatureSet(
            query=query.model_copy(deep=True),
            features=features,
            source=LandUseSourceMeta(
                dataset_id="openstreetmap-overpass-land-use",
                dataset_version=self._cache_version,
                evidence_level=DatasetEvidenceLevel.PUBLIC_OBSERVATION,
                queried_at=queried_at,
                source_uri=self._endpoint,
                license="OpenStreetMap ODbL 1.0",
                record_count=len(features),
                available_record_count=available_count,
            ),
        )

    def _build_query(self, query: LandUseQuery) -> str:
        bbox = (
            f"{query.south:.8f},{query.west:.8f},"
            f"{query.north:.8f},{query.east:.8f}"
        )
        clauses = []
        for element_type in ("way", "relation"):
            clauses.extend(
                [
                    f'{element_type}["landuse"~"^(commercial|retail)$"]({bbox});',
                    f'{element_type}["building"~'
                    f'"^(commercial|retail|supermarket|kiosk)$"]({bbox});',
                ]
            )
        return (
            "[out:json][timeout:25];(" + "".join(clauses) + ");"
            "out tags geom;"
        )


def _parse_overpass_polygon(element: Any):
    if not isinstance(element, dict):
        raise LandUseResponseError("Overpass 用地 element 必须是对象")
    element_type = str(element.get("type", "")).strip()
    element_id = str(element.get("id", "")).strip()
    tags = element.get("tags") or {}
    if element_type not in {"way", "relation"} or not element_id:
        return None
    if not isinstance(tags, dict):
        raise LandUseResponseError("Overpass 用地 tags 必须是对象")
    geometry = (
        _way_polygon(element.get("geometry"))
        if element_type == "way"
        else _relation_polygon(element.get("members"))
    )
    if geometry is None or geometry.is_empty:
        return None
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    return {
        "source_feature_id": f"osm:{element_type}:{element_id}",
        "name": str(tags.get("name") or f"OSM {element_type} {element_id}"),
        "land_use_class": _land_use_class(tags),
        "tags": dict(tags),
        "geometry": geometry,
    }


def _way_polygon(points: Any):
    coordinates = _coordinates(points)
    if len(coordinates) < 4:
        return None
    if coordinates[0] != coordinates[-1]:
        return None
    return Polygon(coordinates)


def _relation_polygon(members: Any):
    if not isinstance(members, list):
        return None
    outer_lines = []
    inner_lines = []
    for member in members:
        if not isinstance(member, dict) or member.get("type") != "way":
            continue
        coordinates = _coordinates(member.get("geometry"))
        if len(coordinates) < 2:
            continue
        line = LineString(coordinates)
        if str(member.get("role", "")) == "inner":
            inner_lines.append(line)
        else:
            outer_lines.append(line)
    if not outer_lines:
        return None
    outer = unary_union(list(polygonize(unary_union(outer_lines))))
    if outer.is_empty:
        return None
    if inner_lines:
        inner = unary_union(list(polygonize(unary_union(inner_lines))))
        if not inner.is_empty:
            outer = outer.difference(inner)
    return outer


def _coordinates(points: Any) -> list[tuple[float, float]]:
    if not isinstance(points, list):
        return []
    coordinates = []
    for point in points:
        if not isinstance(point, dict):
            return []
        try:
            coordinates.append((float(point["lon"]), float(point["lat"])))
        except (KeyError, TypeError, ValueError):
            return []
    return coordinates


def _land_use_class(tags: Mapping[str, Any]) -> str:
    landuse = str(tags.get("landuse", "")).strip()
    if landuse == "retail":
        return "OSM 零售用地"
    if landuse == "commercial":
        return "OSM 商业用地"
    building = str(tags.get("building", "")).strip()
    return f"OSM 商业建筑（{building or '未分类'}）"


def _to_land_use_features(items: list[dict[str, Any]]) -> list[LandUseFeature]:
    if not items:
        return []
    frame = gpd.GeoDataFrame(
        [{key: value for key, value in item.items() if key != "geometry"} for item in items],
        geometry=[item["geometry"] for item in items],
        crs="EPSG:4326",
    )
    projected_crs = frame.estimate_utm_crs()
    if projected_crs is None:
        raise LandUseResponseError("无法为 Overpass 用地图层确定米制投影")
    projected = frame.to_crs(projected_crs)
    centers = projected.geometry.centroid.to_crs("EPSG:4326")
    areas = projected.geometry.area / 10_000
    features = []
    for (_, row), center, area in zip(
        frame.iterrows(), centers, areas, strict=True
    ):
        if area <= 0:
            continue
        features.append(
            LandUseFeature(
                source_feature_id=row["source_feature_id"],
                name=row["name"],
                land_use_class=row["land_use_class"],
                longitude=float(center.x),
                latitude=float(center.y),
                area_hectares=float(area),
                osm_tags=row["tags"],
            )
        )
    return sorted(
        features,
        key=lambda item: (-item.area_hectares, item.source_feature_id),
    )
