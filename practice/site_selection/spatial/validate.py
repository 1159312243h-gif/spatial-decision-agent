from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field
from pyproj import CRS
from pyproj.exceptions import CRSError


class SpatialValidationCode(StrEnum):
    EMPTY_DATASET = "empty_dataset"
    MISSING_GEOMETRY_COLUMN = "missing_geometry_column"
    MISSING_FIELDS = "missing_fields"
    MISSING_CRS = "missing_crs"
    INVALID_CRS = "invalid_crs"
    CRS_MISMATCH = "crs_mismatch"
    CRS_NOT_PROJECTED = "crs_not_projected"
    NULL_GEOMETRY = "null_geometry"
    EMPTY_GEOMETRY = "empty_geometry"
    INVALID_GEOMETRY = "invalid_geometry"


class SpatialValidationError(ValueError):
    """Structured failure raised before a dataset reaches GIS analysis."""

    def __init__(
        self,
        code: SpatialValidationCode,
        message: str,
        *,
        row_indices: Iterable[object] = (),
        missing_fields: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.row_indices = tuple(row_indices)
        self.missing_fields = tuple(missing_fields)


class SpatialValidationResult(BaseModel):
    """Small, serializable audit record for one successful validation."""

    model_config = ConfigDict(extra="forbid")

    crs: str = Field(min_length=1)
    is_projected: bool
    feature_count: int = Field(gt=0)
    geometry_column: str = Field(min_length=1)
    geometry_types: list[str] = Field(min_length=1)
    checked_fields: list[str] = Field(default_factory=list)


def parse_crs(value: Any) -> CRS:
    """Parse any PyProj-supported CRS input into a validated CRS object."""

    if value is None:
        raise SpatialValidationError(
            SpatialValidationCode.MISSING_CRS,
            "空间数据缺少 CRS",
        )
    try:
        return CRS.from_user_input(value)
    except (CRSError, TypeError, ValueError) as exc:
        raise SpatialValidationError(
            SpatialValidationCode.INVALID_CRS,
            f"无法解析空间数据 CRS：{value}",
        ) from exc


def validate_spatial_dataset(
    frame: gpd.GeoDataFrame,
    *,
    required_fields: Iterable[str],
    require_projected: bool = True,
    expected_crs: Any | None = None,
) -> SpatialValidationResult:
    """Validate schema, CRS, and geometry before deterministic GIS analysis."""

    if not isinstance(frame, gpd.GeoDataFrame):
        raise TypeError("空间数据必须是 GeoDataFrame")

    if frame.empty:
        raise SpatialValidationError(
            SpatialValidationCode.EMPTY_DATASET,
            "空间数据不能为空",
        )

    try:
        geometry = frame.geometry
    except AttributeError as exc:
        raise SpatialValidationError(
            SpatialValidationCode.MISSING_GEOMETRY_COLUMN,
            "空间数据缺少活动 geometry 列",
        ) from exc

    checked_fields = list(dict.fromkeys(required_fields))
    missing_fields = [
        field_name
        for field_name in checked_fields
        if field_name not in frame.columns
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise SpatialValidationError(
            SpatialValidationCode.MISSING_FIELDS,
            f"空间数据缺少必需字段：{joined}",
            missing_fields=missing_fields,
        )

    crs = parse_crs(frame.crs)
    if expected_crs is not None:
        declared_crs = parse_crs(expected_crs)
        if not crs.equals(declared_crs):
            raise SpatialValidationError(
                SpatialValidationCode.CRS_MISMATCH,
                (
                    "空间数据实际 CRS 与 DatasetManifest 声明不一致："
                    f"actual={crs.to_string()}, "
                    f"expected={declared_crs.to_string()}"
                ),
            )
    if require_projected and not crs.is_projected:
        raise SpatialValidationError(
            SpatialValidationCode.CRS_NOT_PROJECTED,
            "距离或面积分析必须使用投影坐标系",
        )

    null_mask = geometry.isna()
    if null_mask.any():
        indices = frame.index[null_mask].tolist()
        raise SpatialValidationError(
            SpatialValidationCode.NULL_GEOMETRY,
            f"空间数据包含缺失几何：{indices}",
            row_indices=indices,
        )

    empty_mask = geometry.is_empty
    if empty_mask.any():
        indices = frame.index[empty_mask].tolist()
        raise SpatialValidationError(
            SpatialValidationCode.EMPTY_GEOMETRY,
            f"空间数据包含空几何：{indices}",
            row_indices=indices,
        )

    invalid_mask = ~geometry.is_valid
    if invalid_mask.any():
        indices = frame.index[invalid_mask].tolist()
        raise SpatialValidationError(
            SpatialValidationCode.INVALID_GEOMETRY,
            f"空间数据包含无效几何：{indices}",
            row_indices=indices,
        )

    geometry_types = sorted(set(geometry.geom_type.tolist()))
    return SpatialValidationResult(
        crs=crs.to_string(),
        is_projected=crs.is_projected,
        feature_count=len(frame),
        geometry_column=geometry.name,
        geometry_types=geometry_types,
        checked_fields=checked_fields,
    )
