from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

import geopandas as gpd
from sqlalchemy import text

from ..domain import DatasetManifest, DatasetSource
from .gateway import SpatialDatasetAccessError


_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PostGISReader = Callable[..., gpd.GeoDataFrame]


_STORED_LAYER_SQL = text(
    """
    SELECT
        feature.source_feature_id,
        feature.properties,
        ST_AsBinary(feature.geometry) AS geometry,
        layer.normalized_crs
    FROM site_selection.spatial_features AS feature
    INNER JOIN site_selection.spatial_layers AS layer
        ON layer.layer_id = feature.layer_id
    WHERE layer.layer_id = :layer_id
    ORDER BY feature.feature_id
    """
)


class PostGISSpatialDatasetGateway:
    """Read allowlisted PostGIS relations without accepting arbitrary SQL."""

    def __init__(
        self,
        connection: Any,
        *,
        allowed_schemas: Iterable[str] = ("public",),
        default_schema: str = "public",
        geometry_column: str = "geometry",
        reader: PostGISReader | None = None,
    ) -> None:
        if connection is None:
            raise ValueError("PostGIS Gateway 必须配置数据库连接")

        schemas = tuple(dict.fromkeys(allowed_schemas))
        if not schemas:
            raise ValueError("PostGIS Gateway 至少需要一个 schema 白名单")
        for schema in schemas:
            _require_identifier(schema, field="schema")
        _require_identifier(default_schema, field="default_schema")
        _require_identifier(geometry_column, field="geometry_column")
        if default_schema not in schemas:
            raise ValueError("PostGIS 默认 schema 必须在白名单中")

        self._connection = connection
        self._allowed_schemas = frozenset(schemas)
        self._default_schema = default_schema
        self._geometry_column = geometry_column
        self._reader = reader or gpd.read_postgis

    @property
    def allowed_schemas(self) -> frozenset[str]:
        return self._allowed_schemas

    def load(self, manifest: DatasetManifest) -> gpd.GeoDataFrame:
        schema, table = self._relation_for(manifest)
        sql = f'SELECT * FROM "{schema}"."{table}"'
        try:
            frame = self._reader(
                sql,
                self._connection,
                geom_col=self._geometry_column,
            )
        except Exception as exc:
            raise SpatialDatasetAccessError(
                "postgis_read_failed: "
                f"dataset_id={manifest.dataset_id}, "
                f"error_type={type(exc).__name__}"
            ) from exc
        if not isinstance(frame, gpd.GeoDataFrame):
            raise SpatialDatasetAccessError(
                f"postgis_invalid_result: dataset_id={manifest.dataset_id}"
            )
        return frame.copy(deep=True)

    def _relation_for(self, manifest: DatasetManifest) -> tuple[str, str]:
        if manifest.source is not DatasetSource.POSTGIS:
            raise SpatialDatasetAccessError(
                f"unsupported_source: dataset_id={manifest.dataset_id}"
            )

        parts = manifest.location.split(".")
        if len(parts) == 1:
            schema, table = self._default_schema, parts[0]
        elif len(parts) == 2:
            schema, table = parts
        else:
            raise SpatialDatasetAccessError(
                f"invalid_relation: dataset_id={manifest.dataset_id}"
            )

        try:
            _require_identifier(schema, field="schema")
            _require_identifier(table, field="table")
        except ValueError as exc:
            raise SpatialDatasetAccessError(
                f"invalid_relation: dataset_id={manifest.dataset_id}"
            ) from exc
        if schema not in self._allowed_schemas:
            raise SpatialDatasetAccessError(
                f"schema_not_allowed: dataset_id={manifest.dataset_id}"
            )
        return schema, table


class StoredPostGISSpatialDatasetGateway:
    """Load manifested layers from the normalized site-selection schema."""

    def __init__(
        self,
        connection: Any,
        *,
        reader: PostGISReader | None = None,
    ) -> None:
        if connection is None:
            raise ValueError("Stored PostGIS Gateway 必须配置数据库连接")
        self._connection = connection
        self._reader = reader or gpd.read_postgis

    def load(self, manifest: DatasetManifest) -> gpd.GeoDataFrame:
        if manifest.source is not DatasetSource.POSTGIS:
            raise SpatialDatasetAccessError(
                f"unsupported_source: dataset_id={manifest.dataset_id}"
            )

        try:
            stored = self._reader(
                _STORED_LAYER_SQL,
                self._connection,
                geom_col="geometry",
                params={"layer_id": manifest.location},
            )
        except Exception as exc:
            raise SpatialDatasetAccessError(
                "stored_postgis_read_failed: "
                f"dataset_id={manifest.dataset_id}, "
                f"error_type={type(exc).__name__}"
            ) from exc

        if not isinstance(stored, gpd.GeoDataFrame):
            raise SpatialDatasetAccessError(
                f"stored_postgis_invalid_result: dataset_id={manifest.dataset_id}"
            )
        if stored.empty:
            raise SpatialDatasetAccessError(
                f"stored_postgis_layer_empty: dataset_id={manifest.dataset_id}"
            )

        try:
            frame = _expand_stored_properties(stored, manifest)
            normalized_crs_values = {
                str(value).strip()
                for value in frame.pop("normalized_crs").tolist()
                if str(value).strip()
            }
            if len(normalized_crs_values) != 1:
                raise ValueError("stored layer has inconsistent normalized CRS")
            normalized_crs = normalized_crs_values.pop()
            frame = frame.set_crs(normalized_crs, allow_override=True)
            if manifest.crs is not None and str(frame.crs) != manifest.crs:
                frame = frame.to_crs(manifest.crs)
        except Exception as exc:
            raise SpatialDatasetAccessError(
                "stored_postgis_invalid_result: "
                f"dataset_id={manifest.dataset_id}, "
                f"error_type={type(exc).__name__}"
            ) from exc
        return frame.copy(deep=True)


def _expand_stored_properties(
    stored: gpd.GeoDataFrame,
    manifest: DatasetManifest,
) -> gpd.GeoDataFrame:
    required = {"source_feature_id", "properties", "geometry", "normalized_crs"}
    if not required.issubset(stored.columns):
        missing = sorted(required - set(stored.columns))
        raise ValueError("stored layer result is missing columns: " + ", ".join(missing))

    records: list[dict[str, Any]] = []
    geometries = []
    for _, row in stored.iterrows():
        properties = row["properties"]
        if not isinstance(properties, dict):
            raise ValueError("stored feature properties must be an object")
        record = dict(properties)
        record.setdefault("source_feature_id", str(row["source_feature_id"]))
        record["normalized_crs"] = row["normalized_crs"]
        records.append(record)
        geometries.append(row["geometry"])

    return gpd.GeoDataFrame(
        records,
        geometry=geometries,
        crs=stored.crs,
    )


def _require_identifier(value: str, *, field: str) -> None:
    if not isinstance(value, str) or _SQL_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"PostGIS {field} 不是安全 SQL 标识符")
