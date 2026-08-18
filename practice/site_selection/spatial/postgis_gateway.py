from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

import geopandas as gpd

from ..domain import DatasetManifest, DatasetSource
from .gateway import SpatialDatasetAccessError


_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PostGISReader = Callable[..., gpd.GeoDataFrame]


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


def _require_identifier(value: str, *, field: str) -> None:
    if not isinstance(value, str) or _SQL_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"PostGIS {field} 不是安全 SQL 标识符")
