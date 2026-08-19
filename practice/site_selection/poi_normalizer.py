from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import NonEmptyString


class UnsupportedPOICRSError(ValueError):
    """Raised when coordinates cannot be normalized without a real transform."""


class RawPOI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: NonEmptyString
    source_id: NonEmptyString
    name: NonEmptyString
    category: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    source_crs: NonEmptyString
    address: str | None = None
    fetched_at: datetime
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fetched_at")
    @classmethod
    def fetched_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("POI 抓取时间必须包含时区")
        return value


class NormalizedPOI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: NonEmptyString
    source_id: NonEmptyString
    name: NonEmptyString
    category: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    source_crs: Literal["WGS84", "EPSG:4326"]
    normalized_crs: Literal["EPSG:4326"] = "EPSG:4326"
    address: str | None = None
    fetched_at: datetime
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fetched_at")
    @classmethod
    def fetched_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("POI 抓取时间必须包含时区")
        return value

    @property
    def identity_key(self) -> tuple[str, str]:
        return self.source, self.source_id


class POINormalizer:
    """Normalize reviewed WGS84 POI input without pretending GCJ-02 is WGS84."""

    def __init__(
        self,
        category_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._category_aliases = {
            source.strip(): target.strip()
            for source, target in (category_aliases or {}).items()
        }
        if any(
            not source or not target
            for source, target in self._category_aliases.items()
        ):
            raise ValueError("POI 类别映射不能包含空值")

    def normalize(self, raw: RawPOI) -> NormalizedPOI:
        source_crs = _normalize_source_crs(raw.source_crs)
        category = self._category_aliases.get(raw.category, raw.category)
        return NormalizedPOI(
            source=raw.source.strip().lower(),
            source_id=raw.source_id,
            name=raw.name,
            category=category,
            longitude=raw.longitude,
            latitude=raw.latitude,
            source_crs=source_crs,
            address=raw.address.strip() if raw.address else None,
            fetched_at=raw.fetched_at,
            raw_payload=raw.model_copy(deep=True).raw_payload,
        )

    def normalize_many(self, items: Iterable[RawPOI]) -> list[NormalizedPOI]:
        return [self.normalize(item) for item in items]


def _normalize_source_crs(value: str) -> Literal["WGS84", "EPSG:4326"]:
    normalized = value.strip().upper().replace("_", "-")
    if normalized in {"WGS84", "WGS-84"}:
        return "WGS84"
    if normalized in {"EPSG:4326", "EPSG-4326"}:
        return "EPSG:4326"
    if normalized in {"GCJ02", "GCJ-02"}:
        raise UnsupportedPOICRSError(
            "GCJ-02 必须经过真实坐标转换，不能直接标记为 EPSG:4326"
        )
    raise UnsupportedPOICRSError(f"尚不支持的 POI 源坐标系：{value}")
