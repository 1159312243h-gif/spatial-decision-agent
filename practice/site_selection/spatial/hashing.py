from __future__ import annotations

import json
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
from typing import Any

import geopandas as gpd
import pandas as pd
import shapely

from .validate import validate_spatial_dataset


def stable_spatial_hash(
    frame: gpd.GeoDataFrame,
    *,
    required_fields: tuple[str, ...] = (),
) -> str:
    """Return a row-order-independent SHA-256 hash for valid spatial data."""

    validation = validate_spatial_dataset(
        frame,
        required_fields=required_fields,
        require_projected=False,
        require_metric_units=False,
    )
    geometry_column = validation.geometry_column
    attribute_columns = sorted(
        column for column in frame.columns if column != geometry_column
    )
    rows = []
    for _, row in frame.iterrows():
        geometry = shapely.normalize(row[geometry_column])
        row_payload = {
            "geometry_wkb": shapely.to_wkb(
                geometry,
                hex=True,
                output_dimension=2,
                byte_order=1,
                include_srid=False,
            ),
            "properties": {
                column: _canonical_value(row[column])
                for column in attribute_columns
            },
        }
        rows.append(_canonical_json(row_payload))

    payload = {
        "algorithm": "site-selection-spatial-v1",
        "crs": validation.crs,
        "columns": attribute_columns,
        "rows": sorted(rows),
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except ValueError:
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("空间哈希不接受 NaN 或无穷属性值")
        return 0.0 if value == 0 else value
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(f"空间哈希不支持属性类型：{type(value).__name__}")
