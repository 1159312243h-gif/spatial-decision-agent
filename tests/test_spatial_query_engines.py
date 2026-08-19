import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from practice.site_selection.spatial.query_engine import (
    GeoPandasSpatialQueryEngine,
    PostGISSpatialQueryEngine,
)

from .storage_fakes import FakeConnection, FakeResult


def parcel_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"]},
        geometry=[
            Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
        ],
        crs="EPSG:32651",
    )


def context_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"context_id": ["inside", "outside"]},
        geometry=[Point(50, 50), Point(150, 50)],
        crs="EPSG:32651",
    )


def test_geopandas_engine_returns_shared_metric_contract() -> None:
    result = GeoPandasSpatialQueryEngine().analyze(
        parcel_frame(),
        context_rows=context_frame(),
    )

    assert result.analysis_crs == "EPSG:32651"
    assert result.area_hectares == pytest.approx(1)
    assert result.intersecting_feature_count == 1
    assert result.nearest_feature_distance_m == 0


def test_postgis_engine_uses_bound_parameters_for_target_only() -> None:
    connection = FakeConnection(
        [
            FakeResult(
                [
                    {
                        "area_hectares": 1.0,
                        "intersecting_feature_count": None,
                        "nearest_feature_distance_m": None,
                    }
                ]
            )
        ]
    )

    result = PostGISSpatialQueryEngine(connection).analyze(
        layer_id="candidate-layer",
        source_feature_id="A01",
        analysis_srid=32651,
    )

    sql, parameters = connection.calls[0]
    assert ":layer_id" in sql
    assert ":source_feature_id" in sql
    assert ":analysis_srid" in sql
    assert "candidate-layer" not in sql
    assert parameters == {
        "layer_id": "candidate-layer",
        "source_feature_id": "A01",
        "analysis_srid": 32651,
    }
    assert result is not None
    assert result.area_hectares == 1


def test_postgis_engine_queries_intersection_and_distance_together() -> None:
    connection = FakeConnection(
        [
            FakeResult(
                [
                    {
                        "area_hectares": 1.0,
                        "intersecting_feature_count": 1,
                        "nearest_feature_distance_m": 0.0,
                    }
                ]
            )
        ]
    )

    result = PostGISSpatialQueryEngine(connection).analyze(
        layer_id="candidate-layer",
        source_feature_id="A01",
        analysis_srid=32651,
        context_layer_id="context-layer",
    )

    sql, parameters = connection.calls[0]
    assert "ST_Intersects" in sql
    assert "ST_Distance" in sql
    assert parameters["context_layer_id"] == "context-layer"
    assert result is not None
    assert result.intersecting_feature_count == 1
    assert result.nearest_feature_distance_m == 0


def test_postgis_engine_returns_none_for_missing_target() -> None:
    result = PostGISSpatialQueryEngine(FakeConnection()).analyze(
        layer_id="candidate-layer",
        source_feature_id="missing",
        analysis_srid=32651,
    )

    assert result is None


@pytest.mark.parametrize("analysis_srid", [0, 999_000])
def test_postgis_engine_rejects_invalid_srid(analysis_srid: int) -> None:
    with pytest.raises(ValueError, match="analysis_srid"):
        PostGISSpatialQueryEngine(FakeConnection()).analyze(
            layer_id="candidate-layer",
            source_feature_id="A01",
            analysis_srid=analysis_srid,
        )
