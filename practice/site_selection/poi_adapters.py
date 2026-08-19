from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString
from .poi import POIFeatureSet, POIProvider, POIQuery, POIRecord, POISourceMeta
from .poi_service import calculate_poi_metrics


class POISourceAdapter(Protocol):
    """Provider-neutral adapter that returns normalized POI features."""

    def search(self, query: POIQuery) -> POIFeatureSet: ...


class FixturePOIDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: NonEmptyString
    version: NonEmptyString
    provider: POIProvider = POIProvider.MOCK
    crs: NonEmptyString = "EPSG:4326"
    updated_at: datetime
    records: list[POIRecord] = Field(min_length=30)

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Fixture POI 更新时间必须包含时区")
        return value

    @model_validator(mode="after")
    def fixture_contract_is_supported(self) -> FixturePOIDataset:
        if self.provider is not POIProvider.MOCK:
            raise ValueError("Fixture POI 数据源必须使用 mock provider")
        if self.crs.upper() != "EPSG:4326":
            raise ValueError("Fixture POI 适配器仅支持 EPSG:4326")
        poi_ids = [record.poi_id for record in self.records]
        if len(poi_ids) != len(set(poi_ids)):
            raise ValueError("Fixture POI 编号不能重复")
        if any(record.distance_m is not None for record in self.records):
            raise ValueError("Fixture 原始 POI 不能预置查询相关 distance_m")
        return self


class FixturePOIAdapter:
    """Deterministic JSON-backed adapter with local radius filtering."""

    def __init__(
        self,
        dataset: FixturePOIDataset,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._dataset = dataset.model_copy(deep=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> FixturePOIAdapter:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(FixturePOIDataset.model_validate(payload), clock=clock)

    @property
    def dataset(self) -> FixturePOIDataset:
        return self._dataset.model_copy(deep=True)

    @property
    def cache_token(self) -> str:
        return (
            f"fixture:{self._dataset.dataset_id}:{self._dataset.version}:"
            f"{self._dataset.updated_at.isoformat()}"
        )

    def search(self, query: POIQuery) -> POIFeatureSet:
        records = []
        for record in self._dataset.records:
            if record.category not in query.categories:
                continue
            distance_m = haversine_distance_m(
                query.longitude,
                query.latitude,
                record.longitude,
                record.latitude,
            )
            if distance_m <= query.radius_m:
                records.append(
                    record.model_copy(
                        deep=True,
                        update={"distance_m": distance_m},
                    )
                )
        records.sort(key=lambda item: (item.distance_m or 0, item.poi_id))
        records = records[: query.limit]

        source = POISourceMeta(
            provider=self._dataset.provider,
            dataset_id=self._dataset.dataset_id,
            dataset_version=self._dataset.version,
            dataset_updated_at=self._dataset.updated_at,
            queried_at=self._clock(),
            crs=self._dataset.crs,
            record_count=len(records),
        )
        return POIFeatureSet(
            query=query.model_copy(deep=True),
            records=records,
            source=source,
            metrics=calculate_poi_metrics(query, records),
        )


def haversine_distance_m(
    longitude_a: float,
    latitude_a: float,
    longitude_b: float,
    latitude_b: float,
) -> float:
    """Return great-circle distance for WGS84-like longitude/latitude input."""

    earth_radius_m = 6_371_008.8
    latitude_a_rad = radians(latitude_a)
    latitude_b_rad = radians(latitude_b)
    delta_latitude = latitude_b_rad - latitude_a_rad
    delta_longitude = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_latitude / 2) ** 2
        + cos(latitude_a_rad)
        * cos(latitude_b_rad)
        * sin(delta_longitude / 2) ** 2
    )
    return 2 * earth_radius_m * asin(sqrt(haversine))
