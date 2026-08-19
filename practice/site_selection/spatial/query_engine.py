from __future__ import annotations

from typing import Any, Protocol

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ..domain import NonEmptyString
from ..storage.postgres import SQLConnection
from .analysis import calculate_spatial_metrics


class SpatialQueryMetrics(BaseModel):
    """Shared result contract for GeoPandas and PostGIS calculations."""

    model_config = ConfigDict(extra="forbid")

    analysis_crs: NonEmptyString
    area_hectares: float = Field(ge=0)
    intersecting_feature_count: int | None = Field(default=None, ge=0)
    nearest_feature_distance_m: float | None = Field(default=None, ge=0)


class StoredSpatialQueryBackend(Protocol):
    def analyze(
        self,
        *,
        layer_id: str,
        source_feature_id: str,
        analysis_srid: int,
        context_layer_id: str | None = None,
    ) -> SpatialQueryMetrics | None: ...


class GeoPandasSpatialQueryEngine:
    """Calculate the shared metrics with validated in-memory frames."""

    def analyze(
        self,
        parcel_rows: gpd.GeoDataFrame,
        *,
        context_rows: gpd.GeoDataFrame | None = None,
    ) -> SpatialQueryMetrics:
        metrics = calculate_spatial_metrics(
            parcel_rows,
            buffer_distance_m=1,
            context_rows=context_rows,
        )
        return SpatialQueryMetrics(
            analysis_crs=parcel_rows.crs.to_string(),
            area_hectares=metrics.area_hectares,
            intersecting_feature_count=metrics.intersecting_feature_count,
            nearest_feature_distance_m=metrics.nearest_feature_distance_m,
        )


class PostGISSpatialQueryEngine:
    """Calculate matching metrics from normalized PostGIS feature storage."""

    def __init__(self, connection: SQLConnection) -> None:
        if connection is None:
            raise ValueError("PostGIS 空间查询必须配置数据库连接")
        self._connection = connection

    def analyze(
        self,
        *,
        layer_id: str,
        source_feature_id: str,
        analysis_srid: int,
        context_layer_id: str | None = None,
    ) -> SpatialQueryMetrics | None:
        if not layer_id.strip() or not source_feature_id.strip():
            raise ValueError("图层编号和源要素编号不能为空")
        if not 1 <= analysis_srid <= 998_999:
            raise ValueError("analysis_srid 超出有效范围")

        parameters: dict[str, Any] = {
            "layer_id": layer_id,
            "source_feature_id": source_feature_id,
            "analysis_srid": analysis_srid,
        }
        if context_layer_id is None:
            statement = text(
                """
                SELECT
                    ST_Area(ST_Transform(geometry, :analysis_srid))
                        / 10000.0 AS area_hectares,
                    NULL::integer AS intersecting_feature_count,
                    NULL::double precision AS nearest_feature_distance_m
                FROM site_selection.spatial_features
                WHERE layer_id = :layer_id
                  AND source_feature_id = :source_feature_id
                """
            )
        else:
            if not context_layer_id.strip():
                raise ValueError("上下文图层编号不能为空")
            parameters["context_layer_id"] = context_layer_id
            statement = text(
                """
                WITH target AS (
                    SELECT geometry
                    FROM site_selection.spatial_features
                    WHERE layer_id = :layer_id
                      AND source_feature_id = :source_feature_id
                )
                SELECT
                    ST_Area(ST_Transform(target.geometry, :analysis_srid))
                        / 10000.0 AS area_hectares,
                    COUNT(context.feature_id) FILTER (
                        WHERE ST_Intersects(context.geometry, target.geometry)
                    )::integer AS intersecting_feature_count,
                    MIN(
                        ST_Distance(
                            ST_Transform(context.geometry, :analysis_srid),
                            ST_Transform(target.geometry, :analysis_srid)
                        )
                    ) AS nearest_feature_distance_m
                FROM target
                LEFT JOIN site_selection.spatial_features AS context
                  ON context.layer_id = :context_layer_id
                GROUP BY target.geometry
                """
            )

        row = self._connection.execute(statement, parameters).mappings().first()
        if row is None:
            return None
        return SpatialQueryMetrics(
            analysis_crs=f"EPSG:{analysis_srid}",
            area_hectares=row["area_hectares"],
            intersecting_feature_count=row["intersecting_feature_count"],
            nearest_feature_distance_m=row["nearest_feature_distance_m"],
        )
