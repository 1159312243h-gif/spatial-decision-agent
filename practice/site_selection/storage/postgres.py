from __future__ import annotations

import json
from datetime import datetime
from math import isfinite
from typing import Any, Protocol

import geopandas as gpd
import pandas as pd
import shapely
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from ..domain import DatasetSource, NonEmptyString, ProjectType
from ..spatial.hashing import stable_spatial_hash
from ..spatial.validate import validate_spatial_dataset


class SQLConnection(Protocol):
    def execute(self, statement: Any, parameters: Any = None) -> Any: ...


class ProjectStorageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: NonEmptyString
    project_type: ProjectType
    name: NonEmptyString
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("项目存储时间必须包含时区")
        return value


class SpatialLayerWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: NonEmptyString
    project_id: NonEmptyString | None = None
    name: NonEmptyString
    layer_type: NonEmptyString
    source: DatasetSource
    version: NonEmptyString
    required_fields: list[NonEmptyString] = Field(min_length=1)
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("required_fields")
    @classmethod
    def required_fields_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("图层必需字段不能重复")
        return values

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("图层更新时间必须包含时区")
        return value


class StoredSpatialLayer(SpatialLayerWrite):
    source_crs: NonEmptyString
    normalized_crs: str = "EPSG:4326"
    data_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class StoredSpatialFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: int = Field(gt=0)
    layer_id: NonEmptyString
    source_feature_id: NonEmptyString
    geometry_wkt: NonEmptyString
    properties: dict[str, Any] = Field(default_factory=dict)


class PostgresSpatialRepository:
    """Parameterized persistence for projects, layers, and spatial features."""

    def __init__(self, connection: SQLConnection) -> None:
        if connection is None:
            raise ValueError("PostGIS Repository 必须配置数据库连接")
        self._connection = connection

    def upsert_project(self, project: ProjectStorageRecord) -> None:
        self._connection.execute(
            text(
                """
                INSERT INTO site_selection.projects (
                    project_id, project_type, name, created_at, updated_at
                ) VALUES (
                    :project_id, :project_type, :name, :created_at, :updated_at
                )
                ON CONFLICT (project_id) DO UPDATE SET
                    project_type = EXCLUDED.project_type,
                    name = EXCLUDED.name,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                **project.model_dump(),
                "project_type": project.project_type.value,
            },
        )

    def get_project(self, project_id: str) -> ProjectStorageRecord | None:
        row = self._connection.execute(
            text(
                """
                SELECT project_id, project_type, name, created_at, updated_at
                FROM site_selection.projects
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).mappings().first()
        return ProjectStorageRecord.model_validate(row) if row else None

    def replace_layer(
        self,
        layer: SpatialLayerWrite,
        frame: gpd.GeoDataFrame,
        *,
        source_id_field: str,
    ) -> StoredSpatialLayer:
        validation = validate_spatial_dataset(
            frame,
            required_fields=[*layer.required_fields, source_id_field],
            require_projected=False,
            require_metric_units=False,
        )
        source_crs = validation.crs
        stored = StoredSpatialLayer(
            **layer.model_dump(),
            source_crs=source_crs,
            data_hash=stable_spatial_hash(
                frame,
                required_fields=tuple(
                    dict.fromkeys([*layer.required_fields, source_id_field])
                ),
            ),
        )
        self._upsert_layer(stored)
        self._connection.execute(
            text(
                "DELETE FROM site_selection.spatial_features "
                "WHERE layer_id = :layer_id"
            ),
            {"layer_id": stored.layer_id},
        )

        normalized = frame.to_crs(stored.normalized_crs)
        parameters = [
            _feature_parameters(
                stored.layer_id,
                row,
                geometry_column=normalized.geometry.name,
                source_id_field=source_id_field,
            )
            for _, row in normalized.iterrows()
        ]
        self._connection.execute(
            text(
                """
                INSERT INTO site_selection.spatial_features (
                    layer_id, source_feature_id, geometry, properties
                ) VALUES (
                    :layer_id,
                    :source_feature_id,
                    ST_GeomFromText(:geometry_wkt, 4326),
                    CAST(:properties AS jsonb)
                )
                """
            ),
            parameters,
        )
        return stored

    def get_layer(self, layer_id: str) -> StoredSpatialLayer | None:
        row = self._connection.execute(
            text(
                """
                SELECT
                    layer_id, project_id, name, layer_type, source,
                    source_crs, normalized_crs, version, data_hash,
                    required_fields, updated_at, metadata
                FROM site_selection.spatial_layers
                WHERE layer_id = :layer_id
                """
            ),
            {"layer_id": layer_id},
        ).mappings().first()
        if row is None:
            return None
        return StoredSpatialLayer.model_validate(_mapping_with_json(row))

    def get_feature(
        self,
        layer_id: str,
        source_feature_id: str,
    ) -> StoredSpatialFeature | None:
        row = self._connection.execute(
            text(
                """
                SELECT
                    feature_id, layer_id, source_feature_id,
                    ST_AsText(geometry) AS geometry_wkt,
                    properties
                FROM site_selection.spatial_features
                WHERE layer_id = :layer_id
                  AND source_feature_id = :source_feature_id
                """
            ),
            {
                "layer_id": layer_id,
                "source_feature_id": source_feature_id,
            },
        ).mappings().first()
        if row is None:
            return None
        return StoredSpatialFeature.model_validate(_mapping_with_json(row))

    def _upsert_layer(self, layer: StoredSpatialLayer) -> None:
        parameters = layer.model_dump()
        parameters["source"] = layer.source.value
        parameters["required_fields"] = json.dumps(
            layer.required_fields,
            ensure_ascii=False,
        )
        parameters["metadata"] = json.dumps(
            layer.metadata,
            ensure_ascii=False,
            sort_keys=True,
        )
        self._connection.execute(
            text(
                """
                INSERT INTO site_selection.spatial_layers (
                    layer_id, project_id, name, layer_type, source,
                    source_crs, normalized_crs, version, data_hash,
                    required_fields, updated_at, metadata
                ) VALUES (
                    :layer_id, :project_id, :name, :layer_type, :source,
                    :source_crs, :normalized_crs, :version, :data_hash,
                    CAST(:required_fields AS jsonb), :updated_at,
                    CAST(:metadata AS jsonb)
                )
                ON CONFLICT (layer_id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    name = EXCLUDED.name,
                    layer_type = EXCLUDED.layer_type,
                    source = EXCLUDED.source,
                    source_crs = EXCLUDED.source_crs,
                    normalized_crs = EXCLUDED.normalized_crs,
                    version = EXCLUDED.version,
                    data_hash = EXCLUDED.data_hash,
                    required_fields = EXCLUDED.required_fields,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
                """
            ),
            parameters,
        )


def _feature_parameters(
    layer_id: str,
    row: Any,
    *,
    geometry_column: str,
    source_id_field: str,
) -> dict[str, Any]:
    source_feature_id = str(row[source_id_field]).strip()
    if not source_feature_id:
        raise ValueError("空间要素源编号不能为空")
    properties = {
        str(column): _json_value(value)
        for column, value in row.items()
        if column != geometry_column
    }
    return {
        "layer_id": layer_id,
        "source_feature_id": source_feature_id,
        "geometry_wkt": shapely.to_wkt(
            row[geometry_column],
            rounding_precision=15,
            trim=True,
        ),
        "properties": json.dumps(
            properties,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except ValueError:
            pass
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float):
        if not isfinite(value):
            return None
        return value
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"空间要素属性无法写入 JSON：{type(value).__name__}")


def _mapping_with_json(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("required_fields", "metadata", "properties"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = json.loads(value)
    return result
