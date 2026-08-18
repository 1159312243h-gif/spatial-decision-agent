from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString


class POIMetric(StrEnum):
    COUNT = "count"
    DENSITY_PER_SQ_KM = "density_per_sq_km"
    NEAREST_DISTANCE_M = "nearest_distance_m"
    AVERAGE_DISTANCE_M = "average_distance_m"


class POIProvider(StrEnum):
    AMAP = "amap"
    BAIDU = "baidu"
    POSTGIS = "postgis"
    MOCK = "mock"


class POIQuery(BaseModel):
    """One bounded POI query derived from a parcel and project profile."""

    model_config = ConfigDict(extra="forbid")

    query_id: NonEmptyString
    parcel_id: NonEmptyString
    group_key: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    categories: Annotated[list[NonEmptyString], Field(min_length=1)]
    radius_m: int = Field(ge=100, le=50_000)
    limit: int = Field(default=100, ge=1, le=1_000)

    @field_validator("categories")
    @classmethod
    def categories_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("POI 类别不能重复")
        return values


class POIRecord(BaseModel):
    """Normalized POI record independent of the upstream provider."""

    model_config = ConfigDict(extra="forbid")

    poi_id: NonEmptyString
    name: NonEmptyString
    category: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    distance_m: float | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class POISourceMeta(BaseModel):
    """Provenance and reproducibility fields for a POI response."""

    model_config = ConfigDict(extra="forbid")

    provider: POIProvider
    dataset_id: NonEmptyString
    queried_at: datetime
    crs: NonEmptyString = "EPSG:4326"
    record_count: int = Field(ge=0)

    @field_validator("queried_at")
    @classmethod
    def queried_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("POI 查询时间必须包含时区")
        return value


class POIFeatureSet(BaseModel):
    """POI response, source metadata, and computed numeric metrics."""

    model_config = ConfigDict(extra="forbid")

    query: POIQuery
    records: list[POIRecord] = Field(default_factory=list)
    source: POISourceMeta
    metrics: dict[POIMetric, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_count_matches_records(self) -> POIFeatureSet:
        if self.source.record_count != len(self.records):
            raise ValueError("POI 来源记录数与实际记录数量不一致")
        return self
