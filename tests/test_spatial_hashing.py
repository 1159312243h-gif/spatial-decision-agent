from datetime import datetime, timezone

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from practice.site_selection.spatial.hashing import stable_spatial_hash


def spatial_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": ["A01", "A02"],
            "land_use": ["commercial", "industrial"],
            "updated_at": [
                datetime(2026, 8, 19, tzinfo=timezone.utc),
                datetime(2026, 8, 19, tzinfo=timezone.utc),
            ],
        },
        geometry=[
            Polygon([(0, 0), (10, 0), (10, 10), (0, 0)]),
            Polygon([(20, 20), (30, 20), (30, 30), (20, 20)]),
        ],
        crs="EPSG:32651",
    )


def test_spatial_hash_is_stable_across_repeated_calls() -> None:
    frame = spatial_frame()

    first = stable_spatial_hash(frame, required_fields=("parcel_id",))
    second = stable_spatial_hash(frame, required_fields=("parcel_id",))

    assert first == second
    assert len(first) == 64


def test_spatial_hash_is_independent_of_row_order_and_index() -> None:
    frame = spatial_frame()
    reordered = frame.iloc[::-1].reset_index(drop=True)

    assert stable_spatial_hash(frame) == stable_spatial_hash(reordered)


def test_spatial_hash_normalizes_equivalent_polygon_ring_start() -> None:
    frame = spatial_frame().iloc[[0]].copy()
    equivalent = frame.copy()
    equivalent.geometry = [
        Polygon([(10, 0), (10, 10), (0, 0), (10, 0)])
    ]

    assert stable_spatial_hash(frame) == stable_spatial_hash(equivalent)


def test_spatial_hash_changes_when_attribute_changes() -> None:
    frame = spatial_frame()
    changed = frame.copy()
    changed.loc[0, "land_use"] = "residential"

    assert stable_spatial_hash(frame) != stable_spatial_hash(changed)


def test_spatial_hash_rejects_non_finite_attributes() -> None:
    frame = spatial_frame()
    frame["ratio"] = [float("nan"), 1.0]

    with pytest.raises(ValueError, match="NaN"):
        stable_spatial_hash(frame)
