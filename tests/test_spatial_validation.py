from collections.abc import Callable

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from practice.site_selection.spatial import (
    SpatialValidationCode,
    SpatialValidationError,
    parse_crs,
    validate_spatial_dataset,
)


REQUIRED_FIELDS = ["parcel_id", "land_use"]


def valid_frame(*, crs: str | None = "EPSG:32651") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": ["A01"],
            "land_use": ["commercial"],
        },
        geometry=[Polygon([(300000, 3450000), (300100, 3450000), (300100, 3450100), (300000, 3450000)])],
        crs=crs,
    )


def assert_error(
    expected_code: SpatialValidationCode,
    action: Callable[[], object],
) -> SpatialValidationError:
    with pytest.raises(SpatialValidationError) as exc_info:
        action()
    assert exc_info.value.code is expected_code
    return exc_info.value


def test_valid_projected_dataset_passes() -> None:
    result = validate_spatial_dataset(
        valid_frame(),
        required_fields=REQUIRED_FIELDS,
    )

    assert result.crs == "EPSG:32651"
    assert result.is_projected is True
    assert result.feature_count == 1
    assert result.geometry_column == "geometry"
    assert result.geometry_types == ["Polygon"]


def test_missing_crs_is_rejected() -> None:
    assert_error(
        SpatialValidationCode.MISSING_CRS,
        lambda: validate_spatial_dataset(
            valid_frame(crs=None),
            required_fields=REQUIRED_FIELDS,
        ),
    )


def test_invalid_crs_is_rejected() -> None:
    assert_error(
        SpatialValidationCode.INVALID_CRS,
        lambda: parse_crs("NOT-A-REAL-CRS"),
    )


def test_geographic_crs_is_rejected_for_metric_analysis() -> None:
    frame = valid_frame(crs=None).set_crs("EPSG:4326", allow_override=True)

    assert_error(
        SpatialValidationCode.CRS_NOT_PROJECTED,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )


def test_geographic_crs_can_pass_a_non_metric_gate() -> None:
    frame = valid_frame(crs=None).set_crs("EPSG:4326", allow_override=True)

    result = validate_spatial_dataset(
        frame,
        required_fields=REQUIRED_FIELDS,
        require_projected=False,
    )

    assert result.is_projected is False


def test_missing_required_fields_are_rejected() -> None:
    frame = valid_frame().drop(columns=["land_use"])

    error = assert_error(
        SpatialValidationCode.MISSING_FIELDS,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )

    assert error.missing_fields == ("land_use",)


def test_missing_active_geometry_column_is_rejected() -> None:
    frame = gpd.GeoDataFrame({"parcel_id": ["A01"], "land_use": ["commercial"]})

    assert_error(
        SpatialValidationCode.MISSING_GEOMETRY_COLUMN,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )


def test_null_geometry_is_rejected_separately() -> None:
    frame = gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[None],
        crs="EPSG:32651",
    )

    error = assert_error(
        SpatialValidationCode.NULL_GEOMETRY,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )

    assert error.row_indices == (0,)


def test_empty_geometry_is_rejected_separately() -> None:
    frame = gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[Polygon()],
        crs="EPSG:32651",
    )

    assert_error(
        SpatialValidationCode.EMPTY_GEOMETRY,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )


def test_self_intersecting_geometry_is_rejected() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    frame = gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[bowtie],
        crs="EPSG:32651",
    )

    assert_error(
        SpatialValidationCode.INVALID_GEOMETRY,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )


def test_empty_dataset_is_rejected() -> None:
    frame = gpd.GeoDataFrame(
        {"parcel_id": [], "land_use": []},
        geometry=[],
        crs="EPSG:32651",
    )

    assert_error(
        SpatialValidationCode.EMPTY_DATASET,
        lambda: validate_spatial_dataset(
            frame,
            required_fields=REQUIRED_FIELDS,
        ),
    )


def test_validation_does_not_mutate_input() -> None:
    frame = valid_frame()
    original = frame.copy(deep=True)

    validate_spatial_dataset(frame, required_fields=REQUIRED_FIELDS)

    assert frame.equals(original)
