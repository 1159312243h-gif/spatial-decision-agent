from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import text

from ..domain import NonEmptyString
from ..poi_normalizer import NormalizedPOI
from .postgres import SQLConnection, _mapping_with_json


class StoredPOI(NormalizedPOI):
    model_config = ConfigDict(extra="forbid")

    poi_id: int = Field(gt=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def storage_timestamps_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("POI 存储时间必须包含时区")
        return value


class NearbyPOI(StoredPOI):
    distance_m: float = Field(ge=0)


class PostgresPOIRepository:
    """Idempotent POI writes keyed by source and source_id."""

    def __init__(self, connection: SQLConnection) -> None:
        if connection is None:
            raise ValueError("POI Repository 必须配置数据库连接")
        self._connection = connection

    def upsert_many(self, items: list[NormalizedPOI]) -> int:
        deduplicated = {item.identity_key: item for item in items}
        if not deduplicated:
            return 0
        parameters = [_write_parameters(item) for item in deduplicated.values()]
        self._connection.execute(
            text(
                """
                INSERT INTO site_selection.pois (
                    source, source_id, name, category,
                    source_crs, normalized_crs, geometry,
                    address, fetched_at, raw_payload
                ) VALUES (
                    :source, :source_id, :name, :category,
                    :source_crs, :normalized_crs,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326),
                    :address, :fetched_at, CAST(:raw_payload AS jsonb)
                )
                ON CONFLICT (source, source_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    source_crs = EXCLUDED.source_crs,
                    normalized_crs = EXCLUDED.normalized_crs,
                    geometry = EXCLUDED.geometry,
                    address = EXCLUDED.address,
                    fetched_at = EXCLUDED.fetched_at,
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = NOW()
                """
            ),
            parameters,
        )
        return len(parameters)

    def get(self, source: str, source_id: str) -> StoredPOI | None:
        row = self._connection.execute(
            text(
                _POI_SELECT_COLUMNS
                + " FROM site_selection.pois"
                + " WHERE source = :source AND source_id = :source_id"
            ),
            {"source": source.strip().lower(), "source_id": source_id},
        ).mappings().first()
        return _stored_poi(row) if row else None

    def search_nearby(
        self,
        *,
        longitude: float,
        latitude: float,
        radius_m: float,
        categories: list[NonEmptyString] | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[NearbyPOI]:
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("POI 查询中心坐标超出范围")
        if radius_m <= 0:
            raise ValueError("POI 查询半径必须大于 0")
        if not 1 <= limit <= 1_000:
            raise ValueError("POI 查询数量限制必须在 1 到 1000 之间")

        category_clause = ""
        parameters: dict[str, Any] = {
            "longitude": longitude,
            "latitude": latitude,
            "radius_m": radius_m,
            "limit": limit,
        }
        if categories:
            category_clause = " AND category = ANY(:categories)"
            parameters["categories"] = list(dict.fromkeys(categories))
        source_clause = ""
        if source is not None:
            normalized_source = source.strip().lower()
            if not normalized_source:
                raise ValueError("POI 数据源不能为空")
            source_clause = " AND source = :source"
            parameters["source"] = normalized_source

        rows = self._connection.execute(
            text(
                _POI_SELECT_COLUMNS
                + """
                , ST_Distance(
                    geometry::geography,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
                ) AS distance_m
                FROM site_selection.pois
                WHERE ST_DWithin(
                    geometry::geography,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                    :radius_m
                )
                """
                + category_clause
                + source_clause
                + " ORDER BY distance_m, source, source_id LIMIT :limit"
            ),
            parameters,
        ).mappings().all()
        return [NearbyPOI.model_validate(_mapping_with_json(row)) for row in rows]


_POI_SELECT_COLUMNS = """
SELECT
    poi_id, source, source_id, name, category,
    source_crs, normalized_crs,
    ST_X(geometry) AS longitude,
    ST_Y(geometry) AS latitude,
    address, fetched_at, raw_payload, created_at, updated_at
"""


def _write_parameters(item: NormalizedPOI) -> dict[str, Any]:
    parameters = item.model_dump()
    parameters["raw_payload"] = json.dumps(
        item.raw_payload,
        ensure_ascii=False,
        sort_keys=True,
    )
    return parameters


def _stored_poi(row: Any) -> StoredPOI:
    return StoredPOI.model_validate(_mapping_with_json(row))
