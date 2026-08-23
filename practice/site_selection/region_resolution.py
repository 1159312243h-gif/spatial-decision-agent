from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from math import cos, radians
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .candidate_discovery import DiscoveryBounds
from .scenario import RegionResolution, RegionResolutionSource, RegionResolver


class RegionCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    aliases: list[str] = Field(min_length=1)
    administrative_level: str = Field(min_length=1)
    center_longitude: float = Field(ge=-180, le=180)
    center_latitude: float = Field(ge=-90, le=90)


class FixtureRegionResolver:
    """Offline demonstration resolver; its catalog is not authoritative data."""

    def __init__(self, entries: Sequence[RegionCatalogEntry]) -> None:
        self._entries = list(entries)

    def resolve(
        self,
        region_text: str,
        *,
        radius_km: float,
    ) -> RegionResolution | None:
        normalized = _normalize_region_text(region_text)
        matches = [
            entry
            for entry in self._entries
            if any(
                _normalize_region_text(alias) in normalized
                for alias in [entry.name, *entry.aliases]
            )
        ]
        if not matches:
            return None
        entry = max(matches, key=lambda item: len(item.name))
        return RegionResolution(
            query=region_text,
            normalized_name=entry.name,
            administrative_level=entry.administrative_level,
            center_longitude=entry.center_longitude,
            center_latitude=entry.center_latitude,
            discovery_bounds=bounds_around_center(
                entry.center_longitude,
                entry.center_latitude,
                radius_km,
            ),
            discovery_radius_km=radius_km,
            source=RegionResolutionSource.FIXTURE_CATALOG,
            provider="bundled-region-demo-catalog",
            confidence=0.7,
            warnings=[
                "区域中心来自离线演示目录，不是权威行政边界；正式决策应接入经审核的行政区或规划范围数据。",
                "候选发现使用区域中心周边搜索窗口，并不代表覆盖整个行政区。",
            ],
        )


class AMapRegionResolver:
    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://restapi.amap.com/v3/config/district",
        timeout_seconds: float = 8,
        client_factory: Callable[..., Any] = httpx.Client,
    ) -> None:
        if not api_key.strip():
            raise ValueError("高德区域解析必须配置 API Key")
        self._api_key = api_key.strip()
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def resolve(
        self,
        region_text: str,
        *,
        radius_km: float,
    ) -> RegionResolution | None:
        with self._client_factory(timeout=self._timeout_seconds) as client:
            response = client.get(
                self._endpoint,
                params={
                    "key": self._api_key,
                    "keywords": region_text,
                    "subdistrict": 0,
                    "extensions": "base",
                },
            )
            response.raise_for_status()
            payload = response.json()
        districts = payload.get("districts") or []
        if str(payload.get("status")) != "1" or not districts:
            return None
        district = districts[0]
        longitude, latitude = _parse_location(district.get("center"))
        return RegionResolution(
            query=region_text,
            normalized_name=str(district.get("name") or region_text),
            administrative_level=str(district.get("level") or "unknown"),
            center_longitude=longitude,
            center_latitude=latitude,
            discovery_bounds=bounds_around_center(
                longitude,
                latitude,
                radius_km,
            ),
            discovery_radius_km=radius_km,
            source=RegionResolutionSource.AMAP,
            provider="amap-district-v3",
            confidence=0.9,
            warnings=[
                "候选发现使用解析中心周边搜索窗口，并不代表覆盖整个行政区。",
                "第三方区域解析结果仍需在正式项目中与权威行政边界或项目红线复核。",
            ],
        )


class AutoRegionResolver:
    def __init__(
        self,
        primary: RegionResolver | None,
        fallback: RegionResolver,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def resolve(
        self,
        region_text: str,
        *,
        radius_km: float,
    ) -> RegionResolution | None:
        if self._primary is not None:
            try:
                resolved = self._primary.resolve(region_text, radius_km=radius_km)
                if resolved is not None:
                    return resolved
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        return self._fallback.resolve(region_text, radius_km=radius_km)


def build_region_resolver(
    values: Mapping[str, str],
    entries: Sequence[RegionCatalogEntry],
    *,
    client_factory: Callable[..., Any] = httpx.Client,
) -> RegionResolver:
    provider = values.get("SITE_SELECTION_REGION_PROVIDER", "auto").strip().lower()
    fixture = FixtureRegionResolver(entries)
    if provider == "fixture":
        return fixture
    if provider not in {"auto", "amap"}:
        raise ValueError("SITE_SELECTION_REGION_PROVIDER 只能是 auto、amap 或 fixture")
    api_key = values.get("AMAP_API_KEY", "").strip()
    amap = (
        AMapRegionResolver(
            api_key,
            endpoint=values.get(
                "SITE_SELECTION_AMAP_DISTRICT_ENDPOINT",
                "https://restapi.amap.com/v3/config/district",
            ).strip(),
            timeout_seconds=float(
                values.get("SITE_SELECTION_REGION_TIMEOUT_SECONDS", "8")
            ),
            client_factory=client_factory,
        )
        if api_key
        else None
    )
    if provider == "amap" and amap is None:
        raise ValueError("amap 区域解析模式必须配置 AMAP_API_KEY")
    return AutoRegionResolver(amap, fixture)


def bounds_around_center(
    longitude: float,
    latitude: float,
    radius_km: float,
) -> DiscoveryBounds:
    if radius_km <= 0 or radius_km > 7:
        raise ValueError("候选发现半径必须大于 0 且不超过 7 公里")
    latitude_delta = radius_km / 111.32
    longitude_scale = max(0.2, cos(radians(latitude)))
    longitude_delta = radius_km / (111.32 * longitude_scale)
    return DiscoveryBounds(
        west=longitude - longitude_delta,
        south=latitude - latitude_delta,
        east=longitude + longitude_delta,
        north=latitude + latitude_delta,
    )


def _normalize_region_text(value: str) -> str:
    return "".join(value.strip().lower().split())


def _parse_location(value: Any) -> tuple[float, float]:
    parts = str(value or "").split(",")
    if len(parts) != 2:
        raise ValueError("区域解析响应缺少合法中心坐标")
    return float(parts[0]), float(parts[1])
